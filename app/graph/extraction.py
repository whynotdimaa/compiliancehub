"""Compliance entity extraction: deterministic regex core + optional LLM.

Two extractors, deliberately layered:
- Regex catches well-formed identifiers (ISO 27001, GDPR, "Article 30") —
  deterministic, free, and good enough to make graph search useful without
  any API key. Also the only extractor used on the *query* path (no LLM
  latency on every /search).
- LLM (when a key is configured) catches free-form entities the patterns
  cannot ("data protection officer", obligations). Failures degrade to
  regex-only — extraction must never sink an ingestion.
"""
import enum
import json
import re
from dataclasses import dataclass

import structlog

from app.core.llm import OpenAICompatChatLLM

logger = structlog.get_logger()


class EntityType(enum.StrEnum):
    REGULATION = "regulation"
    STANDARD = "standard"
    REFERENCE = "reference"
    ORGANIZATION = "organization"
    OBLIGATION = "obligation"


@dataclass(frozen=True)
class Entity:
    name: str
    type: EntityType


def normalize(name: str) -> str:
    """Canonical form used for graph identity: 'ISO/IEC  27001' == 'iso/iec 27001'."""
    return re.sub(r"\s+", " ", name).strip().lower()


# --- Regex extractor ---------------------------------------------------------

_KNOWN_REGULATIONS = [
    "GDPR", "HIPAA", "CCPA", "CPRA", "DORA", "NIS2", "NIS 2", "SOX", "PCI DSS",
    "PCI-DSS", "eIDAS", "MiFID II", "PSD2", "AI Act",
]
_KNOWN_STANDARDS = ["SOC 2", "SOC2", "NIST CSF", "NIST 800-53", "CIS Controls"]

_PATTERNS: list[tuple[re.Pattern[str], EntityType]] = [
    (
        re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _KNOWN_REGULATIONS) + r")\b", re.I),
        EntityType.REGULATION,
    ),
    (
        re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _KNOWN_STANDARDS) + r")\b", re.I),
        EntityType.STANDARD,
    ),
    # ISO 27001, ISO/IEC 27001:2022, ISO 9001
    (re.compile(r"\bISO(?:/IEC)?\s?\d{4,5}(?::\d{4})?\b", re.I), EntityType.STANDARD),
    # Article 30, Article 5a
    (re.compile(r"\bArticle\s+\d+[a-z]?\b", re.I), EntityType.REFERENCE),
    # Section 4.2, Clause 9.1.2, Annex A, Annex A.8
    (
        re.compile(r"\b(?:Section|Clause|Annex)\s+[A-Z]?\d*(?:\.\d+)*\b", re.I),
        EntityType.REFERENCE,
    ),
]


class RegexEntityExtractor:
    def extract(self, text: str) -> list[Entity]:
        entities: list[Entity] = []
        for pattern, entity_type in _PATTERNS:
            for match in pattern.finditer(text):
                name = re.sub(r"\s+", " ", match.group(0)).strip()
                if name:
                    entities.append(Entity(name=name, type=entity_type))
        return _dedupe(entities)


# --- LLM extractor -----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You extract compliance-related entities from document text. "
    "Return ONLY a JSON array, no commentary. Each item: "
    '{"name": "<entity>", "type": "<type>"}. '
    f"Allowed types: {', '.join(t.value for t in EntityType)}. "
    "Extract regulations, standards, clause references, organizations and "
    "concrete obligations (e.g. \"appoint a data protection officer\"). "
    "Maximum 15 entities."
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


class LLMEntityExtractor:
    def __init__(self, llm: OpenAICompatChatLLM) -> None:
        self.llm = llm

    def extract(self, text: str) -> list[Entity]:
        try:
            raw = self.llm.complete(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text[:6000]},
                ]
            )
            return _parse_entities(raw)
        except Exception as exc:
            logger.warning("llm_extraction_failed", error=str(exc))
            return []


def _parse_entities(raw: str) -> list[Entity]:
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1)
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    entities: list[Entity] = []
    valid_types = {t.value for t in EntityType}
    for item in items:
        if not isinstance(item, dict):
            continue
        name, entity_type = item.get("name"), item.get("type")
        if isinstance(name, str) and name.strip() and entity_type in valid_types:
            entities.append(Entity(name=name.strip()[:200], type=EntityType(entity_type)))
    return _dedupe(entities)


# --- Composition -------------------------------------------------------------


class CompositeExtractor:
    """Regex always; LLM on top when available. First occurrence wins dedupe."""

    def __init__(self, extractors: list) -> None:
        self.extractors = extractors

    def extract(self, text: str) -> list[Entity]:
        entities: list[Entity] = []
        for extractor in self.extractors:
            entities.extend(extractor.extract(text))
        return _dedupe(entities)


def _dedupe(entities: list[Entity]) -> list[Entity]:
    seen: set[str] = set()
    unique: list[Entity] = []
    for entity in entities:
        norm = normalize(entity.name)
        if norm not in seen:
            seen.add(norm)
            unique.append(entity)
    return unique

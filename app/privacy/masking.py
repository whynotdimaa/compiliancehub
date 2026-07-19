"""PII masking before text leaves the trust boundary (LLM API, web search).

Default engine is regex-based: deterministic, zero heavy dependencies, and
covers the formats that actually leak from corporate documents — emails,
phones, cards, IBANs, IPs. Credit-card candidates are Luhn-validated so
arbitrary long numbers (contract IDs) are not destroyed. Presidio (NER-based,
better recall on person names) is an optional extra: `pip install .[privacy]`
and PII_ENGINE=presidio — a config switch, not a code change.

Scope: masking applies to what the third-party model sees. The API response
still returns the tenant's own unmasked chunks — the reader is authorized to
see their documents; the LLM provider is not.
"""
import re
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class PIIMasker(Protocol):
    def mask(self, text: str) -> str: ...


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+\w")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{2,4}){3,8}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){12,19}\b")
_PHONE_CANDIDATE = re.compile(
    r"(?<![\w/.-])(?:\+\d{1,3}[\s-]?)?(?:\(\d{2,4}\)[\s-]?)?\d{2,4}(?:[\s-]\d{2,6}){1,4}"
    r"(?![\w/.-])"
)
_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class RegexPIIMasker:
    def mask(self, text: str) -> str:
        text = _EMAIL.sub("<EMAIL>", text)
        text = _IBAN.sub("<IBAN>", text)
        text = _CARD_CANDIDATE.sub(self._card, text)
        text = _IPV4.sub("<IP_ADDRESS>", text)
        text = _PHONE_CANDIDATE.sub(self._phone, text)
        return text

    @staticmethod
    def _card(match: re.Match) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return "<CREDIT_CARD>"
        return match.group(0)

    @staticmethod
    def _phone(match: re.Match) -> str:
        candidate = match.group(0)
        if _DATE_PREFIX.match(candidate):  # ISO dates are not phone numbers
            return candidate
        digits = re.sub(r"\D", "", candidate)
        if 9 <= len(digits) <= 15:
            return "<PHONE>"
        return candidate


class PresidioPIIMasker:
    """NER-based engine (spaCy under the hood): better recall on person names,
    ~600MB heavier install. Requires `pip install .[privacy]`."""

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        self._analyzer = AnalyzerEngine()
        self._anonymizer = AnonymizerEngine()

    def mask(self, text: str) -> str:
        results = self._analyzer.analyze(text=text, language="en")
        return self._anonymizer.anonymize(text=text, analyzer_results=results).text


@lru_cache
def get_masker() -> PIIMasker | None:
    if settings.pii_engine == "off":
        return None
    if settings.pii_engine == "presidio":
        return PresidioPIIMasker()
    return RegexPIIMasker()

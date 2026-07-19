"""Hierarchical chunking: sections stay intact, oversized ones split with overlap.

Chunks never cross section boundaries — a chunk mixing the end of "3.2 Data
Retention" with the start of "4 Incident Response" poisons retrieval. Within a
section, paragraphs are greedily packed up to `max_chars`; an oversized
paragraph falls back to sentence packing, then to a hard sliding window.
Overlap applies only between chunks of the same section.

The heading breadcrumb is stored per chunk and prepended at embedding time
(see `embedding_text`), so a chunk saying "the retention period is 5 years"
still embeds near queries about the policy named only in its heading.
"""
import re
from dataclasses import dataclass

from app.core.config import settings
from app.ingestion.parsing import Section

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    index: int
    text: str
    heading_path: str
    page: int | None


def chunk_sections(
    sections: list[Section],
    *,
    max_chars: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    max_chars = max_chars or settings.chunk_max_chars
    overlap = overlap if overlap is not None else settings.chunk_overlap_chars

    chunks: list[Chunk] = []
    for section in sections:
        breadcrumb = " > ".join(section.heading_path)
        for piece in _split_text(section.text, max_chars, overlap):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    heading_path=breadcrumb,
                    page=section.page,
                )
            )
    return chunks


def embedding_text(chunk: Chunk) -> str:
    """Text actually embedded: breadcrumb gives the chunk its lost context."""
    if chunk.heading_path:
        return f"{chunk.heading_path}\n\n{chunk.text}"
    return chunk.text


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if len(paragraphs) == 1:
        paragraphs = [line for line in text.splitlines() if line.strip()]

    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_long_paragraph(paragraph, max_chars, overlap))
            continue
        candidate = f"{current}\n{paragraph}" if current else paragraph
        if len(candidate) > max_chars:
            pieces.append(current)
            # Overlap: carry the tail of the previous chunk into the next one
            # so a fact straddling the boundary is retrievable from both sides.
            tail = current[-overlap:] if overlap else ""
            merged = f"{tail}\n{paragraph}" if tail else paragraph
            current = merged if len(merged) <= max_chars else paragraph
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_long_paragraph(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    sentences = _SENTENCE_END.split(paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # pathological: no sentence boundaries
            step = max_chars - overlap if max_chars > overlap else max_chars
            pieces.append(sentence[:max_chars])
            sentence = sentence[step:]
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces

"""File parsing into heading-aware sections.

Every parser emits a flat list of Section(heading_path, text, page) where
heading_path is the stack of headings above the text ("2 Scope" > "2.1 Terms").
Downstream chunking never re-detects structure — it only packs section text.

Format-specific structure sources:
- PDF (PyMuPDF): no semantic headings exist, so we use a font-size heuristic —
  the dominant span size is "body", larger sizes become heading levels.
- DOCX (python-docx): real `Heading N` paragraph styles; tables are kept in
  document order and rendered as `cell | cell` lines so policy tables survive.
- Markdown: `#` prefixes. TXT: single section.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


class ParsingError(Exception):
    """Unsupported or unreadable file — permanent failure, do not retry."""


@dataclass
class Section:
    heading_path: tuple[str, ...]
    text: str
    page: int | None = None


@dataclass
class _SectionBuilder:
    """Accumulates body lines under a heading stack, flushing on new headings.

    The stack keeps (level, text) pairs instead of positional indexing, so a
    document starting at level 2 (common in extracted fragments) still nests
    correctly: a new heading pops everything at its level or deeper.
    """

    sections: list[Section] = field(default_factory=list)
    _stack: list[tuple[int, str]] = field(default_factory=list)
    _lines: list[str] = field(default_factory=list)
    _page: int | None = None

    def heading(self, level: int, text: str, page: int | None = None) -> None:
        self.flush()
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))
        self._page = page

    def body(self, text: str, page: int | None = None) -> None:
        if not self._lines:
            self._page = page
        self._lines.append(text)

    def flush(self) -> None:
        text = "\n".join(self._lines).strip()
        if text:
            self.sections.append(
                Section(
                    heading_path=tuple(title for _, title in self._stack),
                    text=text,
                    page=self._page,
                )
            )
        self._lines = []

    def build(self) -> list[Section]:
        self.flush()
        return self.sections


def parse_document(filename: str, data: bytes) -> list[Section]:
    extension = Path(filename).suffix.lower()
    parsers = {
        ".pdf": _parse_pdf,
        ".docx": _parse_docx,
        ".md": _parse_markdown,
        ".txt": _parse_text,
    }
    parser = parsers.get(extension)
    if parser is None:
        raise ParsingError(f"Unsupported file type: {extension}")
    try:
        return parser(data)
    except ParsingError:
        raise
    except Exception as exc:
        raise ParsingError(f"Failed to parse {filename}: {exc}") from exc


# --- PDF ---------------------------------------------------------------------

def _parse_pdf(data: bytes) -> list[Section]:
    with fitz.open(stream=data, filetype="pdf") as pdf:
        lines: list[tuple[str, float, int]] = []  # (text, font_size, page_number)
        for page_number, page in enumerate(pdf, start=1):
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:  # 0 = text block
                    continue
                for line in block["lines"]:
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text:
                        continue
                    size = round(max(span["size"] for span in line["spans"]), 1)
                    lines.append((text, size, page_number))

    if not lines:
        raise ParsingError("PDF contains no extractable text (scanned image?)")

    body_size = Counter(size for _, size, _ in lines).most_common(1)[0][0]
    # Sizes clearly above body text become heading levels, largest = level 1.
    heading_sizes = sorted(
        {size for _, size, _ in lines if size > body_size + 0.5}, reverse=True
    )
    level_by_size = {size: level for level, size in enumerate(heading_sizes[:4], start=1)}

    builder = _SectionBuilder()
    for text, size, page_number in lines:
        level = level_by_size.get(size)
        if level is not None and len(text) < 200:
            builder.heading(level, text, page_number)
        else:
            builder.body(text, page_number)
    return builder.build()


# --- DOCX --------------------------------------------------------------------

_HEADING_STYLE = re.compile(r"^Heading (\d)$")


def _iter_docx_blocks(document: DocxDocument):  # type: ignore[valid-type]
    """Paragraphs and tables in true document order (python-docx separates them)."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _parse_docx(data: bytes) -> list[Section]:
    document = DocxDocument(BytesIO(data))
    builder = _SectionBuilder()
    for block in _iter_docx_blocks(document):
        if isinstance(block, Table):
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                builder.body(" | ".join(cells))
            continue
        text = block.text.strip()
        if not text:
            continue
        match = _HEADING_STYLE.match(block.style.name or "")
        if match:
            builder.heading(int(match.group(1)), text)
        else:
            builder.body(text)
    return builder.build()


# --- Markdown / plain text ---------------------------------------------------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def _parse_markdown(data: bytes) -> list[Section]:
    builder = _SectionBuilder()
    for line in data.decode("utf-8", errors="replace").splitlines():
        match = _MD_HEADING.match(line)
        if match:
            builder.heading(len(match.group(1)), match.group(2).strip())
        elif line.strip():
            builder.body(line.rstrip())
    return builder.build()


def _parse_text(data: bytes) -> list[Section]:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    return [Section(heading_path=(), text=text)]

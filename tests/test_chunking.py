from app.ingestion.chunking import chunk_sections, embedding_text
from app.ingestion.parsing import Section

MAX = 200
OVERLAP = 40


def test_short_section_single_chunk():
    sections = [Section(heading_path=("Policy", "Retention"), text="Keep data 5 years.", page=3)]
    chunks = chunk_sections(sections, max_chars=MAX, overlap=OVERLAP)
    assert len(chunks) == 1
    assert chunks[0].text == "Keep data 5 years."
    assert chunks[0].heading_path == "Policy > Retention"
    assert chunks[0].page == 3


def test_long_section_split_with_overlap():
    paragraphs = [f"Paragraph {i} about compliance requirement number {i}." for i in range(20)]
    sections = [Section(heading_path=("Doc",), text="\n\n".join(paragraphs))]
    chunks = chunk_sections(sections, max_chars=MAX, overlap=OVERLAP)

    assert len(chunks) > 1
    assert all(len(c.text) <= MAX for c in chunks)
    # overlap: each next chunk begins with the tail of the previous one
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.text.startswith(prev.text[-OVERLAP:])


def test_chunks_never_cross_section_boundaries():
    sections = [
        Section(heading_path=("A",), text="Alpha content. " * 30),
        Section(heading_path=("B",), text="Beta content. " * 30),
    ]
    chunks = chunk_sections(sections, max_chars=MAX, overlap=OVERLAP)
    for chunk in chunks:
        assert ("Alpha" in chunk.text) != ("Beta" in chunk.text)


def test_huge_paragraph_falls_back_to_sentences():
    text = " ".join(f"Sentence number {i} is here." for i in range(50))
    chunks = chunk_sections([Section(heading_path=(), text=text)], max_chars=MAX, overlap=OVERLAP)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX for c in chunks)


def test_chunk_indexes_are_global_and_sequential():
    sections = [
        Section(heading_path=("A",), text="one"),
        Section(heading_path=("B",), text="two"),
    ]
    chunks = chunk_sections(sections, max_chars=MAX, overlap=OVERLAP)
    assert [c.index for c in chunks] == [0, 1]


def test_embedding_text_prepends_breadcrumb():
    sections = [Section(heading_path=("Policy", "Access"), text="Admins only.")]
    chunk = chunk_sections(sections, max_chars=MAX, overlap=OVERLAP)[0]
    assert embedding_text(chunk) == "Policy > Access\n\nAdmins only."

    bare = chunk_sections([Section(heading_path=(), text="No heading.")], max_chars=MAX)[0]
    assert embedding_text(bare) == "No heading."

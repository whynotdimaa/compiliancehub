"""CRAG agent scenarios with scripted LLM, fake retriever and fake web search.

LLM call order inside the agent is deterministic:
  grade -> (rewrite -> grade) -> generate
so a scripted response queue drives each scenario precisely.
"""
import json
import uuid
from collections import deque

import pytest

from app.documents.models import Document, DocumentChunk, DocumentType
from app.rag.agent import CRAGAgent, _parse_verdicts
from app.rag.web_search import WebResult
from app.retrieval.service import RetrievedChunk


def make_chunk(text: str, heading: str = "Policy") -> RetrievedChunk:
    document = Document(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Data Policy",
        filename="policy.md",
        content_type="text/markdown",
        doc_type=DocumentType.POLICY,
        storage_path="x",
        size_bytes=1,
    )
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=0,
        text=text,
        heading_path=heading,
        page=1,
    )
    return RetrievedChunk(chunk=chunk, document=document, score=1.0)


class ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = deque(responses)
        self.calls: list[list[dict]] = []

    async def acomplete(self, messages, **kwargs) -> str:
        self.calls.append(messages)
        return self.responses.popleft()


class FakeRetriever:
    def __init__(self, batches: list[list[RetrievedChunk]]) -> None:
        self.batches = deque(batches)
        self.queries: list[str] = []

    async def search(self, query, *, top_k=None, doc_types=None):
        self.queries.append(query)
        return self.batches.popleft() if self.batches else []


async def no_web(query: str) -> list[WebResult]:
    raise AssertionError("web search must not be called in this scenario")


async def empty_web(query: str) -> list[WebResult]:
    return []


# --- verdict parsing ---------------------------------------------------------


def test_parse_verdicts_plain_and_fenced():
    assert _parse_verdicts("[true, false]", expected=2) == [True, False]
    assert _parse_verdicts("```json\n[false, true]\n```", expected=2) == [False, True]


def test_parse_verdicts_length_drift_fails_open():
    assert _parse_verdicts("[true]", expected=3) == [True, True, True]
    assert _parse_verdicts("[true, false, true, false]", expected=2) == [True, False]


def test_parse_verdicts_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_verdicts("no idea", expected=2)
    with pytest.raises(ValueError):
        _parse_verdicts("[1, 0]", expected=2)


# --- scenarios ---------------------------------------------------------------


async def test_happy_path_no_correction():
    chunks = [make_chunk("Data kept five years."), make_chunk("Admins export records.")]
    llm = ScriptedLLM(["[true, true]", "Kept for five years [1]."])
    agent = CRAGAgent(retriever=FakeRetriever([chunks]), llm=llm, web_search=no_web)

    outcome = await agent.ask("How long is data kept?")

    assert outcome.answer == "Kept for five years [1]."
    assert [r.chunk.id for r in outcome.chunks] == [c.chunk.id for c in chunks]
    assert outcome.rewritten_query is None
    assert outcome.used_web_search is False
    assert outcome.low_confidence is False
    assert len(llm.calls) == 2  # grade + generate only


async def test_correction_rewrites_and_regrades():
    weak = [make_chunk("Unrelated text.")]
    strong = [make_chunk("Retention period is five years."), make_chunk("See Article 30.")]
    llm = ScriptedLLM(
        [
            "[false]",                       # grade attempt 1: nothing relevant
            "data retention period policy",  # rewrite
            "[true, true]",                  # grade attempt 2
            "Five years [1].",               # generate
        ]
    )
    retriever = FakeRetriever([weak, strong])
    agent = CRAGAgent(retriever=retriever, llm=llm, web_search=no_web)

    outcome = await agent.ask("How long do we keep data?")

    assert outcome.rewritten_query == "data retention period policy"
    assert retriever.queries == ["How long do we keep data?", "data retention period policy"]
    assert len(outcome.chunks) == 2
    assert outcome.used_web_search is False


async def test_web_fallback_when_documents_fail():
    async def fake_web(query: str) -> list[WebResult]:
        return [WebResult(title="EU DORA overview", url="https://x", content="DORA applies…")]

    llm = ScriptedLLM(
        [
            "[false]",       # grade 1
            "DORA scope",    # rewrite
            "[false]",       # grade 2 (still bad)
            "Per the web source [2]…",
        ]
    )
    agent = CRAGAgent(
        retriever=FakeRetriever([[make_chunk("x")], [make_chunk("y")]]),
        llm=llm,
        web_search=fake_web,
    )

    outcome = await agent.ask("Does DORA apply to us?")

    assert outcome.used_web_search is True
    assert outcome.web_results[0].url == "https://x"
    assert outcome.low_confidence is False  # web gave us something


async def test_low_confidence_when_nothing_found():
    llm = ScriptedLLM(
        ["[false]", "rewritten q", "[false]", "I could not find this in the documents."]
    )
    agent = CRAGAgent(
        retriever=FakeRetriever([[make_chunk("x")], [make_chunk("y")]]),
        llm=llm,
        web_search=empty_web,
    )
    outcome = await agent.ask("Something obscure?")
    assert outcome.low_confidence is True
    assert outcome.chunks == []


async def test_grading_failure_fails_open():
    chunks = [make_chunk("A"), make_chunk("B")]
    llm = ScriptedLLM(["absolutely not json", "Answer [1]."])
    agent = CRAGAgent(retriever=FakeRetriever([chunks]), llm=llm, web_search=no_web)

    outcome = await agent.ask("Question here?")
    # grader broke -> all chunks kept -> no correction loop
    assert len(outcome.chunks) == 2
    assert outcome.rewritten_query is None


async def test_rewrite_identical_to_question_skips_second_retrieval():
    llm = ScriptedLLM(
        ["[false]", "How long do we keep data?", "Nothing found."]
    )
    retriever = FakeRetriever([[make_chunk("x")]])
    agent = CRAGAgent(retriever=retriever, llm=llm, web_search=empty_web)

    outcome = await agent.ask("How long do we keep data?")
    assert outcome.rewritten_query is None
    assert len(retriever.queries) == 1

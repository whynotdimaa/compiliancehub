"""Unit tests for hybrid retrieval.

vector_search / fulltext_search need real Postgres (pgvector ops, tsvector) —
covered in tests/integration. Here: RRF math, HybridRetriever orchestration
(fused order -> hydration -> rerank -> top_k) and the /search endpoint, with
the two search functions and both models faked.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.documents.models import Document, DocumentChunk, DocumentStatus, DocumentType
from app.retrieval import service
from app.retrieval.service import HybridRetriever, rrf_fuse
from app.tenants.models import Tenant


@pytest.fixture(autouse=True)
def _no_neo4j(monkeypatch):
    """Unit tests must never open a Bolt connection; tests that exercise the
    graph source override this with their own fake."""

    async def empty_graph(query, *, limit):
        return []

    monkeypatch.setattr(service, "graph_search", empty_graph)

# --- RRF ---------------------------------------------------------------------

A, B, C, D = (uuid.uuid4() for _ in range(4))


def test_rrf_consensus_beats_single_list_top():
    # B appears in both rankings; A and C are single-list leaders
    fused = rrf_fuse([[A, B], [C, B]], k=60)
    assert fused[0] == B


def test_rrf_preserves_rank_order_within_single_list():
    assert rrf_fuse([[A, B, C]], k=60) == [A, B, C]


def test_rrf_empty_rankings():
    assert rrf_fuse([[], []]) == []


def test_rrf_scores_decay_with_rank():
    fused = rrf_fuse([[A, B], [A, C]], k=1)
    assert fused[0] == A  # rank 1 twice
    # B and C both rank 2 once — tie, both present
    assert set(fused[1:]) == {B, C}


# --- HybridRetriever orchestration ------------------------------------------


class FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 384

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 384 for _ in texts]


class FakeReranker:
    """Scores passages by presence of a keyword — deterministic reordering."""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append((query, passages))
        return [1.0 if self.keyword in p else 0.0 for p in passages]


@pytest.fixture
async def seeded(session_factory):
    """Tenant + READY document + three chunks in SQLite."""
    async with session_factory() as session:
        tenant = Tenant(id=uuid.uuid4(), name="Acme", slug="acme")
        document = Document(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            title="Data Policy",
            filename="policy.md",
            content_type="text/markdown",
            doc_type=DocumentType.POLICY,
            storage_path="x",
            size_bytes=1,
            status=DocumentStatus.READY,
        )
        chunks = [
            DocumentChunk(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                document_id=document.id,
                chunk_index=i,
                text=text_,
                heading_path=heading,
            )
            for i, (heading, text_) in enumerate(
                [
                    ("Retention", "Data is kept for five years."),
                    ("Access", "Only administrators may export records."),
                    ("Backups", "Backups are encrypted at rest."),
                ]
            )
        ]
        session.add_all([tenant, document, *chunks])
        await session.commit()
        return document, chunks


async def test_hybrid_search_orchestration(session_factory, seeded, monkeypatch):
    document, chunks = seeded
    retention, access, backups = chunks

    async def fake_vector(session, embedding, *, limit, doc_types=None):
        return [retention.id, access.id]

    async def fake_fulltext(session, query, *, limit, doc_types=None):
        return [backups.id, access.id]

    monkeypatch.setattr(service, "vector_search", fake_vector)
    monkeypatch.setattr(service, "fulltext_search", fake_fulltext)

    reranker = FakeReranker(keyword="Backups")
    async with session_factory() as session:
        retriever = HybridRetriever(session, embedder=FakeEmbedder(), reranker=reranker)
        results = await retriever.search("are backups encrypted?", top_k=3)

    # access is in both rankings -> RRF puts it first, but the reranker
    # promotes the backups chunk to the top
    assert results[0].chunk.id == backups.id
    assert results[0].score == 1.0
    assert {r.chunk.id for r in results} == {retention.id, access.id, backups.id}
    assert all(r.document.id == document.id for r in results)
    # reranker saw breadcrumb-prefixed passages
    assert any(p.startswith("Backups\n\n") for p in reranker.calls[0][1])


async def test_hybrid_search_no_candidates(session_factory, seeded, monkeypatch):
    async def empty(session, *args, **kwargs):
        return []

    monkeypatch.setattr(service, "vector_search", empty)
    monkeypatch.setattr(service, "fulltext_search", empty)

    async with session_factory() as session:
        retriever = HybridRetriever(session, embedder=FakeEmbedder(), reranker=FakeReranker("x"))
        assert await retriever.search("anything") == []


async def test_graph_ranking_is_third_rrf_source(session_factory, seeded, monkeypatch):
    _, chunks = seeded
    retention, access, backups = chunks

    async def fake_vector(session, embedding, *, limit, doc_types=None):
        return [retention.id]

    async def fake_fulltext(session, query, *, limit, doc_types=None):
        return [access.id]

    async def fake_graph(query, *, limit):
        # graph agrees with both: backups mentioned via entity match twice
        return [retention.id, access.id, backups.id]

    monkeypatch.setattr(service, "vector_search", fake_vector)
    monkeypatch.setattr(service, "fulltext_search", fake_fulltext)
    monkeypatch.setattr(service, "graph_search", fake_graph)

    class PassthroughReranker:
        def rerank(self, query, passages):
            return [0.0] * len(passages)  # keep RRF order (sorted is stable)

    async with session_factory() as session:
        retriever = HybridRetriever(
            session, embedder=FakeEmbedder(), reranker=PassthroughReranker()
        )
        results = await retriever.search("gdpr query", top_k=3)

    # retention: vector#1 + graph#1 (two sources) must outrank backups (one source)
    ids = [r.chunk.id for r in results]
    assert set(ids) == {retention.id, access.id, backups.id}
    assert ids.index(retention.id) < ids.index(backups.id)


async def test_graph_failure_does_not_break_search(session_factory, seeded, monkeypatch):
    _, chunks = seeded
    retention = chunks[0]

    async def fake_vector(session, embedding, *, limit, doc_types=None):
        return [retention.id]

    async def fake_fulltext(session, query, *, limit, doc_types=None):
        return []

    async def broken_graph(query, *, limit):
        raise ConnectionError("neo4j is down")

    monkeypatch.setattr(service, "vector_search", fake_vector)
    monkeypatch.setattr(service, "fulltext_search", fake_fulltext)
    monkeypatch.setattr(service, "graph_search", broken_graph)

    async with session_factory() as session:
        retriever = HybridRetriever(session, embedder=FakeEmbedder(), reranker=FakeReranker("x"))
        results = await retriever.search("gdpr query")
    assert [r.chunk.id for r in results] == [retention.id]


async def test_hybrid_search_respects_top_k(session_factory, seeded, monkeypatch):
    _, chunks = seeded
    ids = [c.id for c in chunks]

    async def fake_search(session, *args, **kwargs):
        return ids

    monkeypatch.setattr(service, "vector_search", fake_search)
    monkeypatch.setattr(service, "fulltext_search", fake_search)

    async with session_factory() as session:
        retriever = HybridRetriever(session, embedder=FakeEmbedder(), reranker=FakeReranker("x"))
        results = await retriever.search("q", top_k=1)
    assert len(results) == 1


# --- /search endpoint --------------------------------------------------------

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
SEARCH = "/api/v1/search"

TENANT_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "secret-password-1",
    "admin_full_name": "Admin",
}


async def test_search_endpoint(client: AsyncClient, session_factory, monkeypatch):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    login = await client.post(
        LOGIN,
        json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "secret-password-1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    async with session_factory() as session:
        tenant_id = (await session.scalars(select(Tenant.id))).one()
        document = Document(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title="Data Policy",
            filename="policy.md",
            content_type="text/markdown",
            doc_type=DocumentType.POLICY,
            storage_path="x",
            size_bytes=1,
            status=DocumentStatus.READY,
        )
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=0,
            text="Data is kept for five years.",
            heading_path="Retention",
            page=2,
        )
        session.add_all([document, chunk])
        await session.commit()

    async def fake_search(session, *args, **kwargs):
        return [chunk.id]

    monkeypatch.setattr(service, "vector_search", fake_search)
    monkeypatch.setattr(service, "fulltext_search", fake_search)
    monkeypatch.setattr(service, "get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(service, "get_reranker", lambda: FakeReranker("five years"))

    resp = await client.post(SEARCH, json={"query": "retention period"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "retention period"
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["document_title"] == "Data Policy"
    assert result["heading_path"] == "Retention"
    assert result["page"] == 2
    assert result["score"] == 1.0


async def test_search_requires_auth(client: AsyncClient):
    resp = await client.post(SEARCH, json={"query": "anything"})
    assert resp.status_code == 401


async def test_search_validates_query(client: AsyncClient, session_factory):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    login = await client.post(
        LOGIN,
        json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "secret-password-1"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await client.post(SEARCH, json={"query": "x"}, headers=headers)
    assert resp.status_code == 422

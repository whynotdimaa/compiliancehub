"""Integration: vector search, FTS and RRF against real Postgres.

Uses synthetic orthogonal embeddings — no model download needed: the query
vector equals one chunk's vector, so cosine ranking is deterministic.
Connects as app_user with the tenant GUC bound, exactly like the API.
"""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.documents.models import Document, DocumentChunk, DocumentStatus, DocumentType
from app.retrieval.service import fulltext_search, rrf_fuse, vector_search
from app.tenants.models import Tenant

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run"
    ),
]

DIM = 384


def _unit_vector(axis: int) -> list[float]:
    vector = [0.0] * DIM
    vector[axis] = 1.0
    return vector


@pytest.fixture
async def pg_engine():
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://app_user:app_password@localhost:5433/compliancehub",
    )
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def seeded(pg_engine):
    """Tenant + READY document + three chunks with orthogonal embeddings."""
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_ids = [uuid.uuid4() for _ in range(3)]
    texts = [
        "Data is kept for five years under the retention policy.",
        "Only administrators may export records.",
        "Backups are encrypted at rest.",
    ]

    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            # No Tenant<->Document relationship is mapped, so flush explicitly
            # to guarantee FK insert order (SQLAlchemy only orders via relationships).
            session.add(Tenant(id=tenant_id, name=f"T-{tenant_id.hex[:8]}", slug=tenant_id.hex[:8]))
            await session.flush()
            session.add(
                Document(
                    id=document_id,
                    tenant_id=tenant_id,
                    title="Data Policy",
                    filename="policy.md",
                    content_type="text/markdown",
                    doc_type=DocumentType.POLICY,
                    storage_path="x",
                    size_bytes=1,
                    status=DocumentStatus.READY,
                )
            )
            await session.flush()
            session.add_all(
                DocumentChunk(
                    id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=i,
                    text=texts[i],
                    heading_path="Policy",
                    embedding=_unit_vector(i),
                )
                for i, chunk_id in enumerate(chunk_ids)
            )

    yield factory, tenant_id, chunk_ids

    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)}
            )


async def test_vector_search_ranks_by_cosine(seeded):
    factory, tenant_id, chunk_ids = seeded
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            results = await vector_search(session, _unit_vector(1), limit=3)
    assert results[0] == chunk_ids[1]
    assert set(results) == set(chunk_ids)


async def test_vector_search_filters_doc_type(seeded):
    factory, tenant_id, _ = seeded
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            results = await vector_search(
                session, _unit_vector(0), limit=3, doc_types=[DocumentType.CONTRACT]
            )
    assert results == []


async def test_fulltext_search_finds_exact_terms(seeded):
    factory, tenant_id, chunk_ids = seeded
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            results = await fulltext_search(session, "retention policy", limit=5)
    assert results == [chunk_ids[0]]


async def test_rls_hides_other_tenant_chunks(seeded):
    factory, _, _ = seeded
    other_tenant = uuid.uuid4()
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(other_tenant)},
            )
            vec = await vector_search(session, _unit_vector(0), limit=10)
            fts = await fulltext_search(session, "retention", limit=10)
    assert vec == []
    assert fts == []


async def test_hybrid_rrf_over_real_rankings(seeded):
    factory, tenant_id, chunk_ids = seeded
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            vec = await vector_search(session, _unit_vector(0), limit=3)
            fts = await fulltext_search(session, "five years retention", limit=3)
    fused = rrf_fuse([vec, fts])
    # chunk 0 leads both rankings -> must lead the fused one
    assert fused[0] == chunk_ids[0]

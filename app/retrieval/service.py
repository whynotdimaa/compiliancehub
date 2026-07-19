"""Hybrid retrieval: vector + full-text -> Reciprocal Rank Fusion -> reranking.

Why two retrievers: vector search catches paraphrases ("how long do we keep
records" ~ "retention period") but misses exact identifiers; full-text nails
exact terms ("ISO 27001", "Article 30") but not semantics. RRF fuses the two
rankings without score calibration — raw cosine distances and ts_rank values
live on incomparable scales, ranks do not.

RLS note: every query here runs in a tenant-bound session, so cross-tenant
chunks are invisible at the database level — no tenant_id filters needed.
"""
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenant_context import current_tenant_id
from app.documents.models import Document, DocumentChunk, DocumentStatus, DocumentType
from app.graph.client import get_async_driver
from app.graph.extraction import RegexEntityExtractor, normalize
from app.graph.service import GraphSearcher
from app.ingestion.embeddings import Embedder, get_embedder
from app.retrieval.reranker import Reranker, get_reranker

logger = structlog.get_logger()

_query_entity_extractor = RegexEntityExtractor()


@dataclass
class RetrievedChunk:
    chunk: DocumentChunk
    document: Document
    score: float


async def vector_search(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int,
    doc_types: Sequence[DocumentType] | None = None,
) -> list[uuid.UUID]:
    """Chunk ids ordered by cosine distance (HNSW index scan)."""
    distance = DocumentChunk.embedding.cosine_distance(embedding)
    stmt = (
        select(DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.embedding.is_not(None), Document.status == DocumentStatus.READY)
        .order_by(distance)
        .limit(limit)
    )
    if doc_types:
        stmt = stmt.where(Document.doc_type.in_(doc_types))
    return list(await session.scalars(stmt))


async def fulltext_search(
    session: AsyncSession,
    query: str,
    *,
    limit: int,
    doc_types: Sequence[DocumentType] | None = None,
) -> list[uuid.UUID]:
    """Chunk ids ordered by ts_rank_cd (GIN index on the generated tsvector).

    Textual SQL on purpose: the tsvector column is Postgres-only and not mapped
    in the ORM (see migration 0003). websearch_to_tsquery is injection-safe and
    tolerates raw user input ("data AND retention", quoted phrases).
    """
    filter_clause = "AND d.doc_type::text = ANY(:doc_types)" if doc_types else ""
    stmt = text(
        f"""
        SELECT c.id
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.status = 'ready'
          AND c.text_search @@ websearch_to_tsquery('english', :query)
          {filter_clause}
        ORDER BY ts_rank_cd(c.text_search, websearch_to_tsquery('english', :query)) DESC
        LIMIT :limit
        """
    )
    params: dict = {"query": query, "limit": limit}
    if doc_types:
        params["doc_types"] = [t.value for t in doc_types]
    return list((await session.execute(stmt, params)).scalars())


async def graph_search(query: str, *, limit: int) -> list[uuid.UUID]:
    """Graph ranking: regex entities from the query -> Neo4j traversal.

    Regex-only on the query path (no LLM latency per /search). Neo4j has no
    RLS, so the tenant comes explicitly from the request context.
    """
    tenant_id = current_tenant_id.get()
    entities = _query_entity_extractor.extract(query)
    if tenant_id is None or not entities:
        return []
    searcher = GraphSearcher(get_async_driver())
    return await searcher.search(
        tenant_id=tenant_id,
        entity_norms=[normalize(entity.name) for entity in entities],
        limit=limit,
    )


def rrf_fuse(rankings: Sequence[Sequence[uuid.UUID]], *, k: int | None = None) -> list[uuid.UUID]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1/(k + rank).

    k=60 (the paper's default) damps the head of each ranking so one
    retriever's top hit cannot single-handedly dominate consensus.
    """
    k = k if k is not None else settings.rrf_k
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: scores[item], reverse=True)


class HybridRetriever:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.session = session
        self.embedder = embedder or get_embedder()
        self.reranker = reranker or get_reranker()

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        doc_types: Sequence[DocumentType] | None = None,
    ) -> list[RetrievedChunk]:
        top_k = top_k or settings.search_top_k
        candidates = settings.retrieval_candidates

        query_embedding = self.embedder.embed_query(query)
        vector_ids = await vector_search(
            self.session, query_embedding, limit=candidates, doc_types=doc_types
        )
        fulltext_ids = await fulltext_search(
            self.session, query, limit=candidates, doc_types=doc_types
        )

        graph_ids: list[uuid.UUID] = []
        if settings.graph_search_enabled:
            try:
                graph_ids = await graph_search(query, limit=settings.graph_candidates)
            except Exception as exc:
                # Neo4j being down degrades search quality, never availability
                logger.warning("graph_search_failed", error=str(exc))

        fused_ids = rrf_fuse([vector_ids, fulltext_ids, graph_ids])[: settings.rerank_candidates]
        if not fused_ids:
            return []

        loaded = await self._load(fused_ids, doc_types=doc_types)
        ordered = [loaded[chunk_id] for chunk_id in fused_ids if chunk_id in loaded]

        scores = self.reranker.rerank(query, [_passage(chunk) for chunk, _ in ordered])
        reranked = sorted(
            (
                RetrievedChunk(chunk=chunk, document=document, score=score)
                for (chunk, document), score in zip(ordered, scores, strict=True)
            ),
            key=lambda r: r.score,
            reverse=True,
        )
        return reranked[:top_k]

    async def _load(
        self,
        chunk_ids: Sequence[uuid.UUID],
        *,
        doc_types: Sequence[DocumentType] | None = None,
    ) -> dict[uuid.UUID, tuple[DocumentChunk, Document]]:
        # Re-applies status/doc_type filters: graph candidates come from Neo4j,
        # which knows nothing about them — hydration is the enforcement point.
        stmt = (
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(chunk_ids), Document.status == DocumentStatus.READY)
        )
        if doc_types:
            stmt = stmt.where(Document.doc_type.in_(doc_types))
        rows = await self.session.execute(stmt)
        return {chunk.id: (chunk, document) for chunk, document in rows}


def _passage(chunk: DocumentChunk) -> str:
    """Same breadcrumb+text composition the chunk was embedded with."""
    if chunk.heading_path:
        return f"{chunk.heading_path}\n\n{chunk.text}"
    return chunk.text

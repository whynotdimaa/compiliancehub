"""Graph build task (routed to the `graph` queue, see celery_app.py).

Dispatched by the ingestion task once a document is READY. A graph failure
never flips document status — the document stays searchable via vector+FTS,
search just lacks the graph signal until a retry lands. That asymmetry is the
point of separate queues: graph work is enrichment, not ingestion.
"""
import uuid

import structlog
from sqlalchemy import select

from app.core.celery_app import celery
from app.core.llm import get_llm
from app.core.worker_db import tenant_session
from app.documents.models import Document, DocumentChunk
from app.graph.client import get_sync_driver
from app.graph.extraction import CompositeExtractor, LLMEntityExtractor, RegexEntityExtractor
from app.graph.service import ChunkEntities, GraphWriter

logger = structlog.get_logger()


def build_extractor() -> CompositeExtractor:
    extractors: list = [RegexEntityExtractor()]
    llm = get_llm()
    if llm is not None:
        extractors.append(LLMEntityExtractor(llm))
    return CompositeExtractor(extractors)


@celery.task(name="app.graph.tasks.build_document_graph", bind=True, max_retries=3)
def build_document_graph(self, document_id: str, tenant_id: str) -> None:
    doc_id, ten_id = uuid.UUID(document_id), uuid.UUID(tenant_id)
    log = logger.bind(document_id=document_id, tenant_id=tenant_id)

    with tenant_session(ten_id) as session:
        document = session.get(Document, doc_id)
        if document is None:  # deleted between ingest and graph build
            log.info("graph_build_skipped_missing_document")
            return
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        title, doc_type = document.title, document.doc_type.value

    extractor = build_extractor()
    chunk_entities = [
        ChunkEntities(
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            entities=extractor.extract(chunk.text),
        )
        for chunk in chunks
    ]

    try:
        writer = GraphWriter(get_sync_driver())
        writer.ensure_constraints()
        mentions = writer.rebuild_document(
            tenant_id=ten_id,
            document_id=doc_id,
            title=title,
            doc_type=doc_type,
            chunks=chunk_entities,
        )
    except Exception as exc:
        log.warning("graph_build_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=2**self.request.retries * 10) from exc

    log.info("graph_build_finished", chunks=len(chunks), mentions=mentions)

"""Ingestion pipeline task: MinIO -> parse -> chunk -> embed -> pgvector.

Status flow: PENDING (created by API) -> PROCESSING -> READY | FAILED.

Failure taxonomy:
- ParsingError is permanent: mark FAILED, no retry (re-parsing a broken PDF
  five times produces five identical failures).
- Everything else (MinIO/DB/network) is transient: mark FAILED for visibility
  and re-raise so Celery retries; after max_retries the message dead-letters
  (see celery_app.py DLX config).

Idempotency: task_acks_late means a worker crash re-delivers the message, so
run_ingestion deletes the document's existing chunks before inserting — a
re-run converges to the same state instead of duplicating chunks.
"""
import uuid

import structlog
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core import storage
from app.core.celery_app import celery
from app.core.worker_db import tenant_session
from app.documents.models import Document, DocumentChunk, DocumentStatus
from app.ingestion.chunking import chunk_sections, embedding_text
from app.ingestion.embeddings import Embedder, get_embedder
from app.ingestion.parsing import ParsingError, parse_document

logger = structlog.get_logger()


def run_ingestion(session: Session, document: Document, data: bytes, embedder: Embedder) -> int:
    """Parse, chunk, embed and store; returns chunk count. Pure w.r.t. Celery."""
    sections = parse_document(document.filename, data)
    chunks = chunk_sections(sections)
    vectors = embedder.embed_passages([embedding_text(c) for c in chunks]) if chunks else []

    session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    session.add_all(
        DocumentChunk(
            tenant_id=document.tenant_id,
            document_id=document.id,
            chunk_index=chunk.index,
            text=chunk.text,
            heading_path=chunk.heading_path,
            page=chunk.page,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
    document.status = DocumentStatus.READY
    document.chunk_count = len(chunks)
    document.error = None
    return len(chunks)


@celery.task(name="app.ingestion.tasks.ingest_document", bind=True, max_retries=5)
def ingest_document(self, document_id: str, tenant_id: str) -> None:
    doc_id, ten_id = uuid.UUID(document_id), uuid.UUID(tenant_id)
    log = logger.bind(document_id=document_id, tenant_id=tenant_id)

    with tenant_session(ten_id) as session:
        document = session.get(Document, doc_id)
        if document is None:
            # The API publishes right after flush; its COMMIT lands at request
            # teardown, so we may win the race. Short retry instead of an
            # outbox — see DocumentService.create for the tradeoff.
            raise self.retry(countdown=2)
        document.status = DocumentStatus.PROCESSING
        storage_path, filename = document.storage_path, document.filename

    log.info("ingestion_started", filename=filename)
    try:
        data = storage.download_bytes(storage_path)
        with tenant_session(ten_id) as session:
            document = session.get(Document, doc_id)
            count = run_ingestion(session, document, data, get_embedder())
        # Chunks are committed READY — enrich the knowledge graph asynchronously
        # on its own queue; a graph failure never affects document status.
        from app.graph.tasks import build_document_graph
        from app.integrations.tasks import notify_slack

        build_document_graph.delay(document_id, tenant_id)
        notify_slack.delay(f"✅ Document '{filename}' ingested: {count} chunks ready for audit")
        log.info("ingestion_finished", chunks=count)
    except ParsingError as exc:
        from app.integrations.tasks import notify_slack

        _mark_failed(doc_id, ten_id, str(exc))
        notify_slack.delay(f"❌ Document '{filename}' failed ingestion: {str(exc)[:200]}")
        log.warning("ingestion_failed_permanent", error=str(exc))
    except Exception as exc:
        _mark_failed(doc_id, ten_id, f"{type(exc).__name__}: {exc}")
        log.error("ingestion_failed_transient", error=str(exc))
        raise self.retry(exc=exc, countdown=2**self.request.retries * 5) from exc


def _mark_failed(document_id: uuid.UUID, tenant_id: uuid.UUID, error: str) -> None:
    with tenant_session(tenant_id) as session:
        document = session.get(Document, document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
            document.error = error[:2000]

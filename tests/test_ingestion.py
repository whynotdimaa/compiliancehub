"""run_ingestion unit tests: sync SQLite session + fake embedder.

The Celery wrapper (statuses around retries, DLX) is exercised in integration;
here we verify the core pipeline logic and its idempotency.
"""
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.documents.models import Document, DocumentChunk, DocumentStatus, DocumentType
from app.ingestion.parsing import ParsingError
from app.ingestion.tasks import run_ingestion
from app.tenants.models import Tenant

MD_CONTENT = b"""# Policy
## Retention
Data is kept for five years.
## Access
Only administrators may export records.
"""


class FakeEmbedder:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self.seen.extend(texts)
        return [[0.1] * 384 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 384


@pytest.fixture
def sync_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def document(sync_session):
    tenant = Tenant(id=uuid.uuid4(), name="Acme", slug="acme")
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Policy",
        filename="policy.md",
        content_type="text/markdown",
        doc_type=DocumentType.POLICY,
        storage_path="x/y/policy.md",
        size_bytes=len(MD_CONTENT),
        status=DocumentStatus.PROCESSING,
    )
    sync_session.add_all([tenant, doc])
    sync_session.commit()
    return doc


def test_run_ingestion_creates_chunks_and_marks_ready(sync_session, document):
    embedder = FakeEmbedder()
    count = run_ingestion(sync_session, document, MD_CONTENT, embedder)
    sync_session.commit()

    chunks = sync_session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()
    assert count == len(chunks) > 0
    assert document.status == DocumentStatus.READY
    assert document.chunk_count == count
    assert document.error is None
    # breadcrumb went into the embedded text, not only the stored chunk
    assert any("Policy > Retention" in text for text in embedder.seen)
    retention = next(c for c in chunks if c.heading_path == "Policy > Retention")
    assert "five years" in retention.text


def test_run_ingestion_is_idempotent(sync_session, document):
    embedder = FakeEmbedder()
    first = run_ingestion(sync_session, document, MD_CONTENT, embedder)
    sync_session.commit()
    second = run_ingestion(sync_session, document, MD_CONTENT, embedder)
    sync_session.commit()

    chunks = sync_session.scalars(select(DocumentChunk)).all()
    assert first == second == len(chunks)


def test_run_ingestion_unparsable_raises(sync_session, document):
    document.filename = "policy.xyz"
    with pytest.raises(ParsingError):
        run_ingestion(sync_session, document, b"whatever", FakeEmbedder())

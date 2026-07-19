"""Document lifecycle: upload to MinIO, DB row, dispatch of the ingest task.

MinIO calls are blocking (urllib3 under the hood), so they run in a thread
via anyio — the event loop is never blocked by object storage I/O.
"""
import uuid
from functools import partial

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.documents.models import Document, DocumentStatus, DocumentType
from app.ingestion.tasks import ingest_document


class DocumentNotFoundError(Exception):
    pass


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        filename: str,
        content_type: str,
        doc_type: DocumentType,
        title: str | None,
        data: bytes,
    ) -> Document:
        doc_id = uuid.uuid4()
        storage_path = f"{tenant_id}/{doc_id}/{filename}"

        await anyio.to_thread.run_sync(
            partial(storage.upload_bytes, storage_path, data, content_type)
        )

        document = Document(
            id=doc_id,
            tenant_id=tenant_id,
            uploaded_by=user_id,
            title=title or filename,
            filename=filename,
            content_type=content_type,
            doc_type=doc_type,
            storage_path=storage_path,
            size_bytes=len(data),
            status=DocumentStatus.PENDING,
        )
        self.session.add(document)
        await self.session.flush()

        # The row is only flushed here; COMMIT happens at request teardown
        # (get_tenant_session). The task therefore retries if it wins the race
        # and does not see the row yet — simpler than a transactional outbox
        # and honest about the tradeoff (a crash between COMMIT and publish
        # loses the task; acceptable, the document just stays PENDING and can
        # be re-dispatched).
        ingest_document.delay(str(doc_id), str(tenant_id))
        return document

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Document]:
        result = await self.session.scalars(
            select(Document).order_by(Document.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result)

    async def get(self, document_id: uuid.UUID) -> Document:
        document = await self.session.get(Document, document_id)
        if document is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return document

    async def delete(self, document_id: uuid.UUID) -> None:
        document = await self.get(document_id)
        await anyio.to_thread.run_sync(partial(storage.delete_object, document.storage_path))
        await self.session.delete(document)
        await self.session.flush()

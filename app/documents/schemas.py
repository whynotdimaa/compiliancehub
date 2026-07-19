import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.documents.models import DocumentStatus, DocumentType


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    content_type: str
    doc_type: DocumentType
    status: DocumentStatus
    size_bytes: int
    chunk_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class DocumentStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: DocumentStatus
    chunk_count: int
    error: str | None

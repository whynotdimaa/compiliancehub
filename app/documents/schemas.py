import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.documents.models import DocumentStatus, DocumentType


class ImportUrlRequest(BaseModel):
    url: HttpUrl
    doc_type: DocumentType = DocumentType.OTHER
    title: str | None = Field(default=None, max_length=512)
    filename: str | None = Field(default=None, max_length=512)  # when headers/path lack one


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

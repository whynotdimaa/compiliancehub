import uuid

from pydantic import BaseModel, Field

from app.documents.models import DocumentType


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_types: list[DocumentType] | None = None


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    doc_type: DocumentType
    heading_path: str
    page: int | None
    text: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]

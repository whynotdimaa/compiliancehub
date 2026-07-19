import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.documents.models import DocumentType


class AskRequest(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    doc_types: list[DocumentType] | None = None


class Citation(BaseModel):
    index: int  # the [n] marker used in the answer text
    source_type: Literal["document", "web"]
    snippet: str
    # document sources
    chunk_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    document_title: str | None = None
    heading_path: str | None = None
    page: int | None = None
    # web sources
    url: str | None = None
    title: str | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    rewritten_query: str | None
    used_web_search: bool
    low_confidence: bool

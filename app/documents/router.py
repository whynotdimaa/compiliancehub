import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.auth.deps import CurrentUser, TenantSession, require_role
from app.core.config import settings
from app.documents.models import DocumentType
from app.documents.schemas import DocumentOut, DocumentStatusOut
from app.documents.service import DocumentNotFoundError, DocumentService
from app.tenants.models import User, UserRole

router = APIRouter(prefix="/documents", tags=["documents"])

# Content type is derived from the extension, not trusted from the client.
ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

Uploader = Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.AUDITOR))]
Admin = Annotated[User, Depends(require_role(UserRole.ADMIN))]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    user: Uploader,
    session: TenantSession,
    file: UploadFile,
    doc_type: Annotated[DocumentType, Form()] = DocumentType.OTHER,
    title: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    """Accept a file, store it, and queue ingestion (202: processing is async)."""
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{extension}'; allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds {settings.max_upload_mb} MB limit",
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is empty")

    document = await DocumentService(session).create(
        tenant_id=user.tenant_id,
        user_id=user.id,
        filename=filename,
        content_type=ALLOWED_EXTENSIONS[extension],
        doc_type=doc_type,
        title=title,
        data=data,
    )
    return DocumentOut.model_validate(document)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user: CurrentUser,
    session: TenantSession,
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentOut]:
    documents = await DocumentService(session).list(limit=min(limit, 200), offset=offset)
    return [DocumentOut.model_validate(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID, user: CurrentUser, session: TenantSession
) -> DocumentOut:
    try:
        document = await DocumentService(session).get(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DocumentOut.model_validate(document)


@router.get("/{document_id}/status", response_model=DocumentStatusOut)
async def get_document_status(
    document_id: uuid.UUID, user: CurrentUser, session: TenantSession
) -> DocumentStatusOut:
    """Lightweight polling endpoint for ingestion progress."""
    try:
        document = await DocumentService(session).get(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return DocumentStatusOut.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, user: Admin, session: TenantSession) -> None:
    try:
        await DocumentService(session).delete(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

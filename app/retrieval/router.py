from fastapi import APIRouter

from app.auth.deps import CurrentUser, TenantSession
from app.retrieval.schemas import SearchRequest, SearchResponse, SearchResult
from app.retrieval.service import HybridRetriever

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(data: SearchRequest, user: CurrentUser, session: TenantSession) -> SearchResponse:
    """Hybrid search over the tenant's READY documents, with citations."""
    results = await HybridRetriever(session).search(
        data.query, top_k=data.top_k, doc_types=data.doc_types
    )
    return SearchResponse(
        query=data.query,
        results=[
            SearchResult(
                chunk_id=r.chunk.id,
                document_id=r.document.id,
                document_title=r.document.title,
                filename=r.document.filename,
                doc_type=r.document.doc_type,
                heading_path=r.chunk.heading_path,
                page=r.chunk.page,
                text=r.chunk.text,
                score=r.score,
            )
            for r in results
        ],
    )

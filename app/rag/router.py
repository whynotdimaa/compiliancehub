from fastapi import APIRouter, HTTPException, status

from app.auth.deps import CurrentUser, TenantSession
from app.core.llm import get_llm
from app.rag.agent import AgentOutcome, CRAGAgent
from app.rag.schemas import AskRequest, AskResponse, Citation
from app.rag.web_search import tavily_search
from app.retrieval.service import HybridRetriever

router = APIRouter(prefix="/ask", tags=["rag"])


@router.post("", response_model=AskResponse)
async def ask(data: AskRequest, user: CurrentUser, session: TenantSession) -> AskResponse:
    """CRAG-answered question over the tenant's documents, with citations."""
    llm = get_llm()
    if llm is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "LLM is not configured — set GROQ_API_KEY (or point LLM_BASE_URL at Ollama)",
        )
    agent = CRAGAgent(retriever=HybridRetriever(session), llm=llm, web_search=tavily_search)
    outcome = await agent.ask(data.question, doc_types=data.doc_types)
    return AskResponse(
        question=data.question,
        answer=outcome.answer,
        citations=_citations(outcome),
        rewritten_query=outcome.rewritten_query,
        used_web_search=outcome.used_web_search,
        low_confidence=outcome.low_confidence,
    )


def _citations(outcome: AgentOutcome) -> list[Citation]:
    """Mirrors the numbering of context blocks built in CRAGAgent._generate."""
    citations = [
        Citation(
            index=i,
            source_type="document",
            snippet=r.chunk.text[:300],
            chunk_id=r.chunk.id,
            document_id=r.document.id,
            document_title=r.document.title,
            heading_path=r.chunk.heading_path,
            page=r.chunk.page,
        )
        for i, r in enumerate(outcome.chunks, start=1)
    ]
    offset = len(outcome.chunks)
    citations += [
        Citation(
            index=j,
            source_type="web",
            snippet=w.content[:300],
            url=w.url,
            title=w.title,
        )
        for j, w in enumerate(outcome.web_results, start=offset + 1)
    ]
    return citations

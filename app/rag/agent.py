"""CRAG (Corrective RAG) agent.

Plain-RAG failure mode: retrieval returns plausible-looking but irrelevant
chunks and the LLM confidently answers from them. The corrective loop:

    retrieve -> grade each chunk (one batched LLM call)
      enough relevant?           -> generate
      too few?  rewrite query    -> retrieve again -> grade the new chunks
      still too few? web search  -> add web context (Tavily, optional)
      nothing at all?            -> answer anyway, flagged low_confidence

Design notes:
- Grading is fail-open: if the grader call or its JSON breaks, all chunks
  pass. Answering from unfiltered context beats refusing to answer because
  a meta-call failed.
- The generation prompt forbids claims without [n] citations and inventing
  regulation numbers; citations map 1:1 to the numbered context blocks.
"""
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

from app.core.config import settings
from app.core.llm import OpenAICompatChatLLM
from app.privacy.masking import PIIMasker
from app.rag import prompts
from app.rag.web_search import WebResult
from app.retrieval.service import RetrievedChunk

logger = structlog.get_logger()

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

WebSearchFn = Callable[[str], Awaitable[list[WebResult]]]


@dataclass
class AgentOutcome:
    answer: str
    chunks: list[RetrievedChunk]
    web_results: list[WebResult] = field(default_factory=list)
    rewritten_query: str | None = None
    used_web_search: bool = False
    low_confidence: bool = False


class CRAGAgent:
    def __init__(
        self,
        *,
        retriever,
        llm: OpenAICompatChatLLM,
        web_search: WebSearchFn,
        masker: PIIMasker | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.web_search = web_search
        self.masker = masker

    def _mask(self, text: str) -> str:
        """PII leaves the process only masked (LLM API, web search).
        Retrieval and the response payload keep original text — the tenant
        reads their own documents; the third-party model does not."""
        return self.masker.mask(text) if self.masker else text

    async def ask(self, question: str, *, doc_types=None) -> AgentOutcome:
        log = logger.bind(question=question[:120])
        top_k = settings.rag_max_context_chunks

        chunks = await self.retriever.search(question, top_k=top_k, doc_types=doc_types)
        relevant = await self._grade(question, chunks)
        rewritten: str | None = None

        if len(relevant) < settings.rag_min_relevant:
            rewritten = await self._rewrite(question)
            if rewritten:
                seen = {r.chunk.id for r in relevant}
                more = await self.retriever.search(rewritten, top_k=top_k, doc_types=doc_types)
                fresh = [r for r in more if r.chunk.id not in seen]
                relevant += await self._grade(question, fresh)
                log.info("crag_corrected", rewritten=rewritten, relevant=len(relevant))

        web_results: list[WebResult] = []
        if len(relevant) < settings.rag_min_relevant:
            web_results = await self.web_search(self._mask(question))
            log.info("crag_web_fallback", results=len(web_results))

        relevant = relevant[:top_k]
        answer = await self._generate(question, relevant, web_results)
        return AgentOutcome(
            answer=answer,
            chunks=relevant,
            web_results=web_results,
            rewritten_query=rewritten,
            used_web_search=bool(web_results),
            low_confidence=not relevant and not web_results,
        )

    # --- steps ---------------------------------------------------------------

    async def _grade(
        self, question: str, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        passages = [self._mask(r.chunk.text) for r in chunks]
        try:
            raw = await self.llm.acomplete(
                [
                    {"role": "system", "content": prompts.GRADER_SYSTEM},
                    {
                        "role": "user",
                        "content": prompts.grader_user(self._mask(question), passages),
                    },
                ]
            )
            verdicts = _parse_verdicts(raw, expected=len(chunks))
        except Exception as exc:
            logger.warning("crag_grading_failed", error=str(exc))
            return list(chunks)  # fail-open
        return [chunk for chunk, keep in zip(chunks, verdicts, strict=True) if keep]

    async def _rewrite(self, question: str) -> str | None:
        try:
            raw = await self.llm.acomplete(
                [
                    {"role": "system", "content": prompts.REWRITE_SYSTEM},
                    {"role": "user", "content": self._mask(question)},
                ]
            )
        except Exception as exc:
            logger.warning("crag_rewrite_failed", error=str(exc))
            return None
        rewritten = raw.strip().strip('"').splitlines()[0].strip() if raw.strip() else ""
        return rewritten if rewritten and rewritten.lower() != question.lower() else None

    async def _generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        web_results: list[WebResult],
    ) -> str:
        blocks: list[str] = []
        for i, r in enumerate(chunks, start=1):
            location = r.chunk.heading_path or r.document.title
            page = f", p.{r.chunk.page}" if r.chunk.page else ""
            header = f"[{i}] (Document: {r.document.title} — {location}{page})"
            blocks.append(f"{header}\n{self._mask(r.chunk.text)}")
        offset = len(chunks)
        for j, w in enumerate(web_results, start=offset + 1):
            blocks.append(f"[{j}] (Web: {w.title} — {w.url})\n{w.content}")

        return await self.llm.acomplete(
            [
                {"role": "system", "content": prompts.ANSWER_SYSTEM},
                {"role": "user", "content": prompts.answer_user(self._mask(question), blocks)},
            ],
            max_tokens=2048,
        )


def _parse_verdicts(raw: str, *, expected: int) -> list[bool]:
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1)
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not all(isinstance(v, bool) for v in parsed):
        raise ValueError(f"Grader returned non-boolean array: {raw[:200]}")
    # tolerate length drift: missing verdicts fail-open to True
    verdicts = parsed[:expected]
    verdicts += [True] * (expected - len(verdicts))
    return verdicts

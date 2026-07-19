"""Per-question evaluation: run the production /ask pipeline, then judge it.

The agent under evaluation is the same CRAGAgent the API serves (same masker,
same retriever) — evaluating a special code path would measure nothing. Web
search is disabled during evaluation for reproducibility: metrics must
reflect the tenant's corpus, not whatever the web returned today.
"""
from dataclasses import dataclass

from app.core.llm import OpenAICompatChatLLM
from app.evaluation.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from app.ingestion.embeddings import Embedder
from app.rag.agent import CRAGAgent


@dataclass
class EvalItem:
    question: str
    ground_truth: str | None = None


async def evaluate_item(
    agent: CRAGAgent,
    llm: OpenAICompatChatLLM,
    embedder: Embedder,
    item: EvalItem,
) -> dict:
    outcome = await agent.ask(item.question)
    contexts = [r.chunk.text for r in outcome.chunks]
    return {
        "question": item.question,
        "ground_truth": item.ground_truth,
        "answer": outcome.answer,
        "contexts": contexts,
        "faithfulness": await faithfulness(llm, outcome.answer, contexts),
        "answer_relevancy": await answer_relevancy(llm, embedder, item.question, outcome.answer),
        "context_precision": await context_precision(
            llm, item.question, contexts, item.ground_truth
        ),
        "context_recall": await context_recall(llm, item.ground_truth, contexts),
        "low_confidence": outcome.low_confidence,
    }

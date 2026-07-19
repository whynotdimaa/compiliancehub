"""RAGAS metrics (faithfulness, answer relevancy, context precision/recall)
implemented natively on our LLM abstraction.

Why not the `ragas` library: it drags in the langchain stack for what is,
per metric, one or two judge calls and some arithmetic. The definitions below
follow the RAGAS paper; implementing them keeps the dependency tree flat,
works with any OpenAI-compatible provider we already support, and makes the
math unit-testable with a scripted LLM.

Every metric returns None (not 0) when it cannot be computed — a parse
failure or missing ground truth must not poison averages.
"""
import json
import math
import re

from app.core.config import settings
from app.core.llm import OpenAICompatChatLLM
from app.ingestion.embeddings import Embedder

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _json_list(raw: str) -> list | None:
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _bools(raw: str, expected: int) -> list[bool] | None:
    parsed = _json_list(raw)
    if parsed is None or not all(isinstance(v, bool) for v in parsed):
        return None
    # strict here (unlike CRAG grading): a missing verdict counts as False —
    # an eval metric must not inflate itself when the judge under-answers
    verdicts = parsed[:expected]
    return verdicts + [False] * (expected - len(verdicts))


def _numbered(items: list[str], clip: int = 1500) -> str:
    return "\n\n".join(f"[{i}] {item[:clip]}" for i, item in enumerate(items, start=1))


# --- faithfulness ------------------------------------------------------------

_CLAIMS_SYSTEM = (
    "Break the answer into short standalone factual claims. "
    "Reply ONLY with a JSON array of strings. No commentary."
)
_FAITHFUL_SYSTEM = (
    "For each numbered claim, reply true if it is supported by the context, "
    "false otherwise. Reply ONLY with a JSON array of booleans, one per claim."
)


async def faithfulness(
    llm: OpenAICompatChatLLM, answer: str, contexts: list[str]
) -> float | None:
    """Fraction of answer claims supported by the retrieved context."""
    if not answer.strip() or not contexts:
        return None
    raw = await llm.acomplete(
        [
            {"role": "system", "content": _CLAIMS_SYSTEM},
            {"role": "user", "content": answer},
        ]
    )
    claims = _json_list(raw)
    if not claims or not all(isinstance(c, str) for c in claims):
        return None
    raw = await llm.acomplete(
        [
            {"role": "system", "content": _FAITHFUL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Context:\n{_numbered(contexts)}\n\nClaims:\n{_numbered(claims, clip=300)}"
                ),
            },
        ]
    )
    verdicts = _bools(raw, expected=len(claims))
    if verdicts is None:
        return None
    return sum(verdicts) / len(verdicts)


# --- answer relevancy --------------------------------------------------------

_GEN_QUESTIONS_SYSTEM = (
    "Generate {n} short questions that the given answer directly answers. "
    "Reply ONLY with a JSON array of strings."
)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def answer_relevancy(
    llm: OpenAICompatChatLLM, embedder: Embedder, question: str, answer: str
) -> float | None:
    """Mean cosine similarity between the original question and questions
    regenerated from the answer — an evasive answer regenerates different
    questions and scores low, without needing ground truth."""
    if not answer.strip():
        return None
    n = settings.eval_relevancy_questions
    raw = await llm.acomplete(
        [
            {"role": "system", "content": _GEN_QUESTIONS_SYSTEM.format(n=n)},
            {"role": "user", "content": answer},
        ]
    )
    generated = _json_list(raw)
    if not generated or not all(isinstance(q, str) for q in generated):
        return None
    original = embedder.embed_query(question)
    similarities = [_cosine(original, embedder.embed_query(q)) for q in generated]
    return sum(similarities) / len(similarities)


# --- context precision -------------------------------------------------------

_PRECISION_SYSTEM = (
    "For each numbered context passage, reply true if it is useful for "
    "answering the question{gt_hint}, false otherwise. "
    "Reply ONLY with a JSON array of booleans, one per passage."
)


async def context_precision(
    llm: OpenAICompatChatLLM,
    question: str,
    contexts: list[str],
    ground_truth: str | None = None,
) -> float | None:
    """Average Precision over the ranked contexts: relevant chunks must also
    be ranked high, not just present."""
    if not contexts:
        return None
    gt_hint = " (the reference answer is given)" if ground_truth else ""
    user = f"Question: {question}\n"
    if ground_truth:
        user += f"Reference answer: {ground_truth}\n"
    user += f"\nContexts:\n{_numbered(contexts)}"
    raw = await llm.acomplete(
        [
            {"role": "system", "content": _PRECISION_SYSTEM.format(gt_hint=gt_hint)},
            {"role": "user", "content": user},
        ]
    )
    verdicts = _bools(raw, expected=len(contexts))
    if verdicts is None:
        return None
    relevant_total = sum(verdicts)
    if relevant_total == 0:
        return 0.0
    average_precision = 0.0
    seen_relevant = 0
    for position, is_relevant in enumerate(verdicts, start=1):
        if is_relevant:
            seen_relevant += 1
            average_precision += seen_relevant / position
    return average_precision / relevant_total


# --- context recall ----------------------------------------------------------

_RECALL_SYSTEM = (
    "For each numbered statement from the reference answer, reply true if the "
    "context contains the information to support it, false otherwise. "
    "Reply ONLY with a JSON array of booleans, one per statement."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


async def context_recall(
    llm: OpenAICompatChatLLM, ground_truth: str | None, contexts: list[str]
) -> float | None:
    """Fraction of ground-truth statements attributable to the retrieved
    context — did retrieval actually fetch what the right answer needs?"""
    if not ground_truth or not contexts:
        return None
    statements = [s.strip() for s in _SENTENCE_SPLIT.split(ground_truth) if len(s.strip()) > 10]
    if not statements:
        statements = [ground_truth.strip()]
    raw = await llm.acomplete(
        [
            {"role": "system", "content": _RECALL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Context:\n{_numbered(contexts)}\n\n"
                    f"Statements:\n{_numbered(statements, clip=300)}"
                ),
            },
        ]
    )
    verdicts = _bools(raw, expected=len(statements))
    if verdicts is None:
        return None
    return sum(verdicts) / len(verdicts)

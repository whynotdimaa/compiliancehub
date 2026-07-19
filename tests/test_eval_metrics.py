"""Metric math with a scripted judge — deterministic, no network."""
from collections import deque

from app.evaluation.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)


class ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = deque(responses)

    async def acomplete(self, messages, **kwargs) -> str:
        return self.responses.popleft()


CONTEXTS = ["Data is kept five years.", "Backups are encrypted."]


async def test_faithfulness_fraction_of_supported_claims():
    llm = ScriptedLLM(['["kept five years", "deleted after"]', "[true, false]"])
    assert await faithfulness(llm, "Kept five years, deleted after.", CONTEXTS) == 0.5


async def test_faithfulness_none_without_contexts_or_claims():
    assert await faithfulness(ScriptedLLM([]), "Answer.", []) is None
    llm = ScriptedLLM(["not json at all"])
    assert await faithfulness(llm, "Answer.", CONTEXTS) is None


async def test_faithfulness_missing_verdicts_count_as_unsupported():
    llm = ScriptedLLM(['["a", "b", "c", "d"]', "[true, true]"])
    assert await faithfulness(llm, "Answer.", CONTEXTS) == 0.5


class DirectionalEmbedder:
    """'original' maps to x-axis; generated questions to known directions."""

    VECTORS = {
        "How long is data kept?": [1.0, 0.0],
        "same": [1.0, 0.0],
        "orthogonal": [0.0, 1.0],
    }

    def embed_query(self, text: str) -> list[float]:
        return self.VECTORS[text]

    def embed_passages(self, texts):
        return [self.embed_query(t) for t in texts]


async def test_answer_relevancy_mean_cosine():
    llm = ScriptedLLM(['["same", "orthogonal"]'])
    score = await answer_relevancy(
        llm, DirectionalEmbedder(), "How long is data kept?", "Five years."
    )
    assert score == 0.5  # cos=1.0 and cos=0.0 averaged


async def test_answer_relevancy_none_on_parse_failure():
    llm = ScriptedLLM(["no json"])
    assert await answer_relevancy(llm, DirectionalEmbedder(), "q", "answer") is None


async def test_context_precision_is_average_precision():
    # verdicts [true, false, true]: AP = (1/1 + 2/3) / 2 = 0.8333…
    llm = ScriptedLLM(["[true, false, true]"])
    score = await context_precision(llm, "q", ["c1", "c2", "c3"])
    assert abs(score - (1.0 + 2 / 3) / 2) < 1e-9


async def test_context_precision_rank_matters():
    # same relevant count, worse ranking -> lower score
    llm_good = ScriptedLLM(["[true, true, false]"])
    llm_bad = ScriptedLLM(["[false, true, true]"])
    good = await context_precision(llm_good, "q", ["a", "b", "c"])
    bad = await context_precision(llm_bad, "q", ["a", "b", "c"])
    assert good > bad


async def test_context_precision_zero_when_nothing_relevant():
    llm = ScriptedLLM(["[false, false]"])
    assert await context_precision(llm, "q", ["a", "b"]) == 0.0


async def test_context_recall_fraction_of_supported_statements():
    ground_truth = "Data is kept five years. Exports are admin-only. Backups are encrypted."
    llm = ScriptedLLM(["[true, false, true]"])
    assert await context_recall(llm, ground_truth, CONTEXTS) == 2 / 3


async def test_context_recall_none_without_ground_truth():
    assert await context_recall(ScriptedLLM([]), None, CONTEXTS) is None
    assert await context_recall(ScriptedLLM([]), "gt sentence here.", []) is None

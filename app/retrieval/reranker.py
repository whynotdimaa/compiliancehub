"""Cross-encoder reranking via fastembed (ONNX), same rationale as embeddings.

A bi-encoder (BGE embeddings) scores query and passage independently — fast but
lossy. The cross-encoder reads query+passage together and is far more accurate,
but O(candidates) forward passes — which is why it only sees the top fused
candidates, never the whole corpus.

Import is lazy: loading the model costs ~1s and ~300MB; only the first /search
request pays it, and tests inject a fake instead.
"""
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class Reranker(Protocol):
    def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class FastEmbedReranker:
    def __init__(self, model_name: str) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(model_name)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [float(score) for score in self._model.rerank(query, passages)]


@lru_cache
def get_reranker() -> FastEmbedReranker:
    return FastEmbedReranker(settings.reranker_model)

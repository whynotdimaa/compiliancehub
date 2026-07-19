"""Embeddings via fastembed (ONNX runtime).

Why fastembed over sentence-transformers: same BGE weights, but ONNX runtime
instead of a full torch install — the worker image stays ~10x smaller and
CPU inference is faster. The model downloads on first use and is cached in
the HuggingFace cache dir.

The import is lazy: the API process imports this module (via the task module)
but must never pay the model-loading cost — only the worker calls get_embedder().
"""
from functools import lru_cache
from typing import Protocol

from app.core.config import settings


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        # query_embed applies the model's query instruction prefix
        # (BGE: "Represent this sentence for searching relevant passages: ...")
        return next(self._model.query_embed(text)).tolist()


@lru_cache
def get_embedder() -> FastEmbedEmbedder:
    return FastEmbedEmbedder(settings.embedding_model)

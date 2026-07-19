"""Minimal OpenAI-compatible chat client. Groq by default; Ollama by base_url.

Why not the groq/openai SDKs: the surface we need is one JSON POST. A thin
httpx wrapper keeps the dependency tree flat and makes the provider swap
(Groq -> Ollama -> vLLM) a base_url change in config, not a code path.

Sync `complete` serves Celery workers (entity extraction); async `acomplete`
serves API request paths (CRAG agent, Phase 5).
"""
from functools import lru_cache

import httpx

from app.core.config import settings

Message = dict[str, str]  # {"role": ..., "content": ...}


class LLMError(Exception):
    pass


class OpenAICompatChatLLM:
    def __init__(
        self, *, base_url: str, api_key: str, model: str, timeout: float = 60.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    def _payload(self, messages: list[Message], temperature: float, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    @staticmethod
    def _content(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected completion response shape: {data}") from exc

    def complete(
        self, messages: list[Message], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> str:
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=self._payload(messages, temperature, max_tokens),
            )
        if response.status_code != 200:
            raise LLMError(f"LLM request failed ({response.status_code}): {response.text[:500]}")
        return self._content(response.json())

    async def acomplete(
        self, messages: list[Message], *, temperature: float = 0.0, max_tokens: int = 1024
    ) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=self._payload(messages, temperature, max_tokens),
            )
        if response.status_code != 200:
            raise LLMError(f"LLM request failed ({response.status_code}): {response.text[:500]}")
        return self._content(response.json())


@lru_cache
def get_llm() -> OpenAICompatChatLLM | None:
    """None when no API key is configured — callers degrade gracefully."""
    if not settings.groq_api_key:
        return None
    return OpenAICompatChatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.groq_api_key,
        model=settings.groq_model,
    )

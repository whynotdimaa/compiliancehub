import pytest
from httpx import AsyncClient

from app.rag import router as rag_router
from app.rag.web_search import tavily_search
from tests.test_rag_agent import FakeRetriever, ScriptedLLM, make_chunk

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ASK = "/api/v1/ask"

TENANT_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "secret-password-1",
    "admin_full_name": "Admin",
}


@pytest.fixture
async def headers(client: AsyncClient) -> dict[str, str]:
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    login = await client.post(
        LOGIN,
        json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "secret-password-1"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_ask_returns_answer_with_citations(client: AsyncClient, headers, monkeypatch):
    chunks = [
        make_chunk("Data is kept for five years.", heading="Retention"),
        make_chunk("Retention applies to all records.", heading="Scope"),
    ]
    llm = ScriptedLLM(["[true, true]", "Data is kept for five years [1]."])

    monkeypatch.setattr(rag_router, "get_llm", lambda: llm)
    monkeypatch.setattr(
        rag_router, "HybridRetriever", lambda session: FakeRetriever([chunks])
    )

    resp = await client.post(ASK, json={"question": "How long is data kept?"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "Data is kept for five years [1]."
    assert body["low_confidence"] is False
    assert body["used_web_search"] is False
    citation = body["citations"][0]
    assert citation["index"] == 1
    assert citation["source_type"] == "document"
    assert citation["document_title"] == "Data Policy"
    assert citation["heading_path"] == "Retention"


async def test_ask_503_without_llm(client: AsyncClient, headers, monkeypatch):
    monkeypatch.setattr(rag_router, "get_llm", lambda: None)
    resp = await client.post(ASK, json={"question": "Anything at all?"}, headers=headers)
    assert resp.status_code == 503


async def test_ask_requires_auth(client: AsyncClient):
    resp = await client.post(ASK, json={"question": "How long is data kept?"})
    assert resp.status_code == 401


async def test_ask_validates_question_length(client: AsyncClient, headers):
    resp = await client.post(ASK, json={"question": "hi"}, headers=headers)
    assert resp.status_code == 422


async def test_tavily_without_key_returns_empty():
    assert await tavily_search("anything") == []

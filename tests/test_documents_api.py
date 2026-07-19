import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.tenants.models import Tenant, User, UserRole

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
DOCS = "/api/v1/documents"

TENANT_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "secret-password-1",
    "admin_full_name": "Admin",
}

MD_FILE = ("policy.md", b"# Policy\n\nData is kept 5 years.\n", "text/markdown")


@pytest.fixture(autouse=True)
def mock_infra(monkeypatch):
    """Upload tests never touch MinIO or RabbitMQ: storage and dispatch faked."""
    state = {"uploaded": {}, "dispatched": []}

    def fake_upload(path, data, content_type):
        state["uploaded"][path] = (data, content_type)
        return path

    monkeypatch.setattr("app.core.storage.upload_bytes", fake_upload)
    monkeypatch.setattr(
        "app.core.storage.delete_object", lambda path: state["uploaded"].pop(path, None)
    )
    monkeypatch.setattr(
        "app.ingestion.tasks.ingest_document.delay",
        lambda *args, **kwargs: state["dispatched"].append(args),
    )
    return state


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"tenant_slug": "acme", "email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    return await _login(client, "admin@acme.com", "secret-password-1")


@pytest.fixture
async def viewer_headers(client: AsyncClient, session_factory, admin_headers) -> dict[str, str]:
    async with session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == "acme"))
        session.add(
            User(
                tenant_id=tenant.id,
                email="viewer@acme.com",
                hashed_password=hash_password("viewer-password-1"),
                role=UserRole.VIEWER,
            )
        )
        await session.commit()
    return await _login(client, "viewer@acme.com", "viewer-password-1")


async def test_upload_accepted_and_dispatched(client: AsyncClient, admin_headers, mock_infra):
    resp = await client.post(
        DOCS, headers=admin_headers, files={"file": MD_FILE}, data={"doc_type": "policy"}
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["doc_type"] == "policy"
    assert body["title"] == "policy.md"

    assert len(mock_infra["dispatched"]) == 1
    document_id, _tenant_id = mock_infra["dispatched"][0]
    assert document_id == body["id"]
    assert any(body["id"] in path for path in mock_infra["uploaded"])


async def test_upload_custom_title(client: AsyncClient, admin_headers):
    resp = await client.post(
        DOCS, headers=admin_headers, files={"file": MD_FILE}, data={"title": "GDPR Policy v2"}
    )
    assert resp.status_code == 202
    assert resp.json()["title"] == "GDPR Policy v2"


async def test_upload_unsupported_extension(client: AsyncClient, admin_headers):
    resp = await client.post(
        DOCS, headers=admin_headers, files={"file": ("run.exe", b"MZ", "application/x-msdownload")}
    )
    assert resp.status_code == 415


async def test_upload_empty_file(client: AsyncClient, admin_headers):
    resp = await client.post(
        DOCS, headers=admin_headers, files={"file": ("empty.md", b"", "text/markdown")}
    )
    assert resp.status_code == 422


async def test_upload_forbidden_for_viewer(client: AsyncClient, viewer_headers, mock_infra):
    resp = await client.post(DOCS, headers=viewer_headers, files={"file": MD_FILE})
    assert resp.status_code == 403
    assert mock_infra["dispatched"] == []


async def test_upload_requires_auth(client: AsyncClient):
    resp = await client.post(DOCS, files={"file": MD_FILE})
    assert resp.status_code == 401


async def test_list_and_get_and_status(client: AsyncClient, admin_headers, viewer_headers):
    upload = await client.post(DOCS, headers=admin_headers, files={"file": MD_FILE})
    document_id = upload.json()["id"]

    listed = await client.get(DOCS, headers=viewer_headers)
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [document_id]

    got = await client.get(f"{DOCS}/{document_id}", headers=viewer_headers)
    assert got.status_code == 200
    assert got.json()["filename"] == "policy.md"

    status_resp = await client.get(f"{DOCS}/{document_id}/status", headers=viewer_headers)
    assert status_resp.status_code == 200
    assert status_resp.json() == {
        "id": document_id,
        "status": "pending",
        "chunk_count": 0,
        "error": None,
    }


async def test_get_missing_document_404(client: AsyncClient, admin_headers):
    resp = await client.get(
        f"{DOCS}/00000000-0000-0000-0000-000000000000", headers=admin_headers
    )
    assert resp.status_code == 404


async def test_delete_admin_only(client: AsyncClient, admin_headers, viewer_headers, mock_infra):
    upload = await client.post(DOCS, headers=admin_headers, files={"file": MD_FILE})
    document_id = upload.json()["id"]

    forbidden = await client.delete(f"{DOCS}/{document_id}", headers=viewer_headers)
    assert forbidden.status_code == 403

    deleted = await client.delete(f"{DOCS}/{document_id}", headers=admin_headers)
    assert deleted.status_code == 204
    assert mock_infra["uploaded"] == {}

    gone = await client.get(f"{DOCS}/{document_id}", headers=admin_headers)
    assert gone.status_code == 404

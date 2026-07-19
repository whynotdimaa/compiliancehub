import pytest
from httpx import AsyncClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"

TENANT_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "secret-password-1",
    "admin_full_name": "Admin",
}


async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_register_tenant(client: AsyncClient):
    resp = await client.post(REGISTER, json=TENANT_PAYLOAD)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "acme"
    assert "id" in body


async def test_register_duplicate_slug_conflict(client: AsyncClient):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    resp = await client.post(REGISTER, json=TENANT_PAYLOAD)
    assert resp.status_code == 409


async def test_login_and_me(client: AsyncClient):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    resp = await client.post(
        LOGIN,
        json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "secret-password-1"},
    )
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    assert tokens["token_type"] == "bearer"

    me = await client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "admin@acme.com"
    assert me.json()["role"] == "admin"


async def test_login_wrong_password(client: AsyncClient):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    resp = await client.post(
        LOGIN, json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "wrong"}
    )
    assert resp.status_code == 401


async def test_refresh_flow(client: AsyncClient):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    login = await client.post(
        LOGIN,
        json={"tenant_slug": "acme", "email": "admin@acme.com", "password": "secret-password-1"},
    )
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(REFRESH, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # access token must not work as refresh token
    access_token = login.json()["access_token"]
    bad = await client.post(REFRESH, json={"refresh_token": access_token})
    assert bad.status_code == 401


async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get(ME)
    assert resp.status_code == 401


@pytest.mark.parametrize("slug", ["Bad Slug", "UPPER", "with_underscore!"])
async def test_register_invalid_slug(client: AsyncClient, slug: str):
    payload = {**TENANT_PAYLOAD, "tenant_slug": slug}
    resp = await client.post(REGISTER, json=payload)
    assert resp.status_code == 422

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_password
from app.evaluation import router as eval_router
from app.evaluation.models import EvaluationRecord
from app.tenants.models import Tenant, User, UserRole

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
RUNS = "/api/v1/evaluation/runs"

TENANT_PAYLOAD = {
    "tenant_name": "Acme Corp",
    "tenant_slug": "acme",
    "admin_email": "admin@acme.com",
    "admin_password": "secret-password-1",
    "admin_full_name": "Admin",
}


@pytest.fixture(autouse=True)
def dispatched(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        eval_router.run_evaluation, "delay", lambda *args, **kwargs: calls.append(args)
    )
    return calls


async def _login(client, email, password):
    resp = await client.post(
        LOGIN, json={"tenant_slug": "acme", "email": email, "password": password}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client: AsyncClient):
    await client.post(REGISTER, json=TENANT_PAYLOAD)
    return await _login(client, "admin@acme.com", "secret-password-1")


@pytest.fixture
async def viewer_headers(client: AsyncClient, session_factory, admin_headers):
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


async def test_start_run_with_golden_dataset(client: AsyncClient, admin_headers, dispatched):
    resp = await client.post(RUNS, json={}, headers=admin_headers)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["items"] >= 5  # bundled golden dataset
    assert len(dispatched) == 1
    run_id, _tenant_id, dataset_name, items = dispatched[0]
    assert run_id == body["run_id"]
    assert dataset_name == "golden"
    assert all("question" in item for item in items)


async def test_start_run_with_custom_items(client: AsyncClient, admin_headers, dispatched):
    payload = {
        "dataset_name": "smoke",
        "items": [{"question": "How long is data kept?", "ground_truth": "Five years."}],
    }
    resp = await client.post(RUNS, json=payload, headers=admin_headers)
    assert resp.status_code == 202
    assert resp.json()["items"] == 1


async def test_start_run_forbidden_for_viewer(client: AsyncClient, viewer_headers, dispatched):
    resp = await client.post(RUNS, json={}, headers=viewer_headers)
    assert resp.status_code == 403
    assert dispatched == []


async def test_runs_aggregation(client: AsyncClient, admin_headers, session_factory):
    run_id = uuid.uuid4()
    async with session_factory() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == "acme"))
        session.add_all(
            [
                EvaluationRecord(
                    tenant_id=tenant.id,
                    run_id=run_id,
                    dataset_name="golden",
                    question="q1",
                    answer="a1",
                    faithfulness=1.0,
                    answer_relevancy=0.8,
                    context_precision=0.5,
                    context_recall=None,  # must be excluded from AVG, not counted as 0
                ),
                EvaluationRecord(
                    tenant_id=tenant.id,
                    run_id=run_id,
                    dataset_name="golden",
                    question="q2",
                    answer="a2",
                    faithfulness=0.5,
                    answer_relevancy=0.6,
                    context_precision=None,
                    context_recall=1.0,
                ),
            ]
        )
        await session.commit()

    resp = await client.get(RUNS, headers=admin_headers)
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    summary = runs[0]
    assert summary["items"] == 2
    assert summary["avg_faithfulness"] == 0.75
    assert abs(summary["avg_answer_relevancy"] - 0.7) < 1e-9
    assert summary["avg_context_precision"] == 0.5  # NULL excluded
    assert summary["avg_context_recall"] == 1.0

    detail = await client.get(f"{RUNS}/{run_id}", headers=admin_headers)
    assert detail.status_code == 200
    assert [r["question"] for r in detail.json()] == ["q1", "q2"]


async def test_run_details_404(client: AsyncClient, admin_headers):
    resp = await client.get(f"{RUNS}/{uuid.uuid4()}", headers=admin_headers)
    assert resp.status_code == 404


async def test_runs_require_auth(client: AsyncClient):
    assert (await client.get(RUNS)).status_code == 401
    assert (await client.post(RUNS, json={})).status_code == 401

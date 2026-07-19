"""Integration test: PostgreSQL Row-Level Security actually isolates tenants.

Run against the docker-compose Postgres (published on host port 5433):
    DATABASE_URL=postgresql+asyncpg://app_user:app_password@localhost:5433/compliancehub \
    pytest tests/integration -m integration

Requires migrations applied (`make migrate`). Must connect as the non-superuser
app_user role — superusers (compliance) bypass RLS entirely.
"""
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to run"
    ),
]


@pytest.fixture
async def pg_engine():
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://app_user:app_password@localhost:5433/compliancehub",
    )
    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


async def test_rls_blocks_cross_tenant_select(pg_engine):
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    t1, t2 = uuid.uuid4(), uuid.uuid4()

    async with factory() as session:
        async with session.begin():
            for tid, slug in ((t1, f"t1-{t1.hex[:8]}"), (t2, f"t2-{t2.hex[:8]}")):
                await session.execute(
                    text("INSERT INTO tenants (id, name, slug) VALUES (:id, :name, :slug)"),
                    {"id": str(tid), "name": f"Tenant {slug}", "slug": slug},
                )
                await session.execute(
                    text(
                        "INSERT INTO users (tenant_id, email, hashed_password) "
                        "VALUES (:tid, :email, 'x')"
                    ),
                    {"tid": str(tid), "email": f"user@{slug}.com"},
                )

    # Bind tenant 1 → must see only tenant 1's user
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(t1)},
            )
            rows = (await session.execute(text("SELECT tenant_id FROM users"))).scalars().all()
            assert all(str(r) == str(t1) for r in rows)
            assert len(rows) >= 1

    # Cleanup
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id IN (:a, :b)"),
                {"a": str(t1), "b": str(t2)},
            )

"""Unit-level test setup.

RLS is a PostgreSQL feature, so unit tests run against SQLite for speed and
verify application logic; RLS itself is covered by integration tests
(tests/integration, requires docker-compose Postgres).
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session, get_tenant_session
from app.core.tenant_context import current_tenant_id
from app.documents.models import Document, DocumentChunk  # noqa: F401
from app.main import app
from app.tenants.models import Tenant, User  # noqa: F401


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    async def override_get_tenant_session():
        # SQLite: emulate RLS by filtering nothing; app-level tenant checks
        # still apply. Real RLS covered in integration tests. Mirrors the
        # production dependency's transaction: COMMIT at request teardown.
        tenant_id = current_tenant_id.get()
        if tenant_id is None:
            raise RuntimeError("Tenant context is not set")
        async with session_factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_tenant_session] = override_get_tenant_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)

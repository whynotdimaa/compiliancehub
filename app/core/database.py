"""Async SQLAlchemy setup with PostgreSQL Row-Level Security tenant isolation.

Every request-scoped session executes `SET LOCAL app.current_tenant_id = '<uuid>'`
inside its transaction. RLS policies on tenant-scoped tables filter rows by this
setting, so isolation is enforced by the database itself — even a buggy query
in application code cannot leak another tenant's data.
"""
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.tenant_context import current_tenant_id


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=settings.debug,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Plain session — used for auth/registration (no tenant bound yet)."""
    async with async_session_factory() as session:
        yield session


async def get_tenant_session() -> AsyncGenerator[AsyncSession, None]:
    """Tenant-scoped session: applies RLS via SET LOCAL inside the transaction."""
    tenant_id: uuid.UUID | None = current_tenant_id.get()
    if tenant_id is None:
        raise RuntimeError("Tenant context is not set — use auth dependency first")

    async with async_session_factory() as session:
        async with session.begin():
            # set_config(..., is_local => true) == SET LOCAL, but unlike SET it
            # accepts bind parameters (SET is a utility command — no binds).
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            yield session

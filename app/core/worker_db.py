"""Synchronous SQLAlchemy access for Celery workers.

Celery tasks are synchronous, so the worker uses a separate sync engine
(psycopg) instead of running an event loop per task. RLS applies to workers
exactly as to the API: tenant_session() binds `app.current_tenant_id` via
SET LOCAL before any tenant-scoped table is touched — a task handed the wrong
tenant_id sees zero rows instead of another tenant's data.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

sync_engine = create_engine(
    settings.database_url.replace("+asyncpg", "+psycopg"),
    pool_pre_ping=True,
    pool_size=5,
)

sync_session_factory = sessionmaker(sync_engine, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """One transaction with RLS bound to the given tenant; commits on exit."""
    with sync_session_factory() as session:
        with session.begin():
            # set_config(..., true) == SET LOCAL but accepts bind parameters
            session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            yield session

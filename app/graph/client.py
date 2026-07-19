"""Neo4j drivers: sync for Celery workers, async for API request paths.

Multi-tenancy note: Neo4j Community has no RLS and no multi-database, so
tenant isolation here is by convention — every node carries tenant_id and
every query filters on it (see service.py). This is weaker than the Postgres
guarantee and is called out as a deliberate tradeoff; Enterprise would use
one database per tenant.
"""
from functools import lru_cache

from neo4j import AsyncDriver, AsyncGraphDatabase, Driver, GraphDatabase

from app.core.config import settings

_async_driver: AsyncDriver | None = None


@lru_cache
def get_sync_driver() -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )


def get_async_driver() -> AsyncDriver:
    global _async_driver
    if _async_driver is None:
        _async_driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
    return _async_driver


async def close_async_driver() -> None:
    global _async_driver
    if _async_driver is not None:
        await _async_driver.close()
        _async_driver = None

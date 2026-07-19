import asyncio

from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/deep")
async def health_deep() -> dict:
    """Checks every infrastructure dependency. Used by monitoring, not by k8s liveness."""
    results: dict[str, str] = {}

    async def check_postgres() -> None:
        from app.core.database import async_session_factory

        try:
            async with async_session_factory() as session:
                await session.execute(text("SELECT 1"))
            results["postgres"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["postgres"] = f"error: {exc}"

    async def check_redis() -> None:
        try:
            import redis.asyncio as aioredis

            from app.core.config import settings

            client = aioredis.from_url(settings.redis_url)
            await client.ping()
            await client.aclose()
            results["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["redis"] = f"error: {exc}"

    async def check_neo4j() -> None:
        try:
            from neo4j import AsyncGraphDatabase

            from app.core.config import settings

            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )
            await driver.verify_connectivity()
            await driver.close()
            results["neo4j"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["neo4j"] = f"error: {exc}"

    async def check_rabbitmq() -> None:
        try:
            from kombu import Connection

            from app.core.config import settings

            def _probe() -> None:
                with Connection(settings.rabbitmq_url, connect_timeout=3) as conn:
                    conn.connect()

            await asyncio.to_thread(_probe)
            results["rabbitmq"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["rabbitmq"] = f"error: {exc}"

    async def check_minio() -> None:
        try:
            from app.core.storage import get_minio_client

            await asyncio.to_thread(lambda: get_minio_client().list_buckets())
            results["minio"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["minio"] = f"error: {exc}"

    await asyncio.gather(
        check_postgres(), check_redis(), check_neo4j(), check_rabbitmq(), check_minio()
    )
    status = "ok" if all(v == "ok" for v in results.values()) else "degraded"
    return {"status": status, "services": results}

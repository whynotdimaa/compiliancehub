"""Evaluation run task (routed to the `evaluation` queue).

Runs the async /ask pipeline inside the sync worker via asyncio.run. The
engine is created per run with NullPool and disposed at the end — pooled
asyncpg connections must not outlive the event loop they were created in.
"""
import asyncio
import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery
from app.core.config import settings
from app.core.llm import get_llm
from app.core.tenant_context import current_tenant_id
from app.evaluation.models import EvaluationRecord
from app.evaluation.service import EvalItem, evaluate_item
from app.ingestion.embeddings import get_embedder
from app.privacy.masking import get_masker
from app.rag.agent import CRAGAgent
from app.rag.web_search import WebResult
from app.retrieval.service import HybridRetriever

logger = structlog.get_logger()


async def _no_web(query: str) -> list[WebResult]:
    return []  # reproducibility: eval measures the corpus, not today's web


@celery.task(name="app.evaluation.tasks.run_evaluation", bind=True, max_retries=1)
def run_evaluation(self, run_id: str, tenant_id: str, dataset_name: str, items: list[dict]):
    llm = get_llm()
    if llm is None:
        logger.error("evaluation_skipped_no_llm", run_id=run_id)
        return
    asyncio.run(_run(uuid.UUID(run_id), uuid.UUID(tenant_id), dataset_name, items, llm))


async def _run(run_id: uuid.UUID, tenant_id: uuid.UUID, dataset_name: str, items, llm) -> None:
    log = logger.bind(run_id=str(run_id), tenant_id=str(tenant_id))
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    embedder = get_embedder()
    token = current_tenant_id.set(tenant_id)  # graph_search reads the ContextVar
    try:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                    {"tid": str(tenant_id)},
                )
                agent = CRAGAgent(
                    retriever=HybridRetriever(session),
                    llm=llm,
                    web_search=_no_web,
                    masker=get_masker(),
                )
                for raw_item in items:
                    item = EvalItem(
                        question=raw_item["question"],
                        ground_truth=raw_item.get("ground_truth"),
                    )
                    result = await evaluate_item(agent, llm, embedder, item)
                    session.add(
                        EvaluationRecord(
                            tenant_id=tenant_id,
                            run_id=run_id,
                            dataset_name=dataset_name,
                            **result,
                        )
                    )
        log.info("evaluation_finished", items=len(items))
        from app.integrations.tasks import notify_slack

        notify_slack.delay(
            f"📊 Evaluation run '{dataset_name}' finished: {len(items)} questions scored"
        )
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()

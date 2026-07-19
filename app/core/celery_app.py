"""Celery configured with RabbitMQ as broker and Redis as result backend.

Why RabbitMQ over Redis as broker:
- real message acknowledgements (task survives worker crash mid-execution),
- dead-letter exchange for poisoned messages,
- per-queue routing (ingestion is heavy, notifications are light —
  they must not compete for the same consumers).
"""
from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings

celery = Celery(
    "compliancehub",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
)

dead_letter_exchange = Exchange("dlx", type="direct")

celery.conf.update(
    task_acks_late=True,                 # ack only after task finishes
    task_reject_on_worker_lost=True,     # requeue if worker dies
    worker_prefetch_multiplier=1,        # fair dispatch for long ingestion tasks
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_default_queue="ingestion",
    task_queues=(
        Queue(
            "ingestion",
            routing_key="ingestion",
            queue_arguments={"x-dead-letter-exchange": "dlx",
                             "x-dead-letter-routing-key": "dead.ingestion"},
        ),
        Queue(
            "graph",
            routing_key="graph",
            queue_arguments={"x-dead-letter-exchange": "dlx",
                             "x-dead-letter-routing-key": "dead.graph"},
        ),
        Queue("notifications", routing_key="notifications"),
        Queue("dead_letter", dead_letter_exchange, routing_key="dead.#"),
    ),
    task_routes={
        "app.ingestion.tasks.*": {"queue": "ingestion"},
        "app.graph.tasks.*": {"queue": "graph"},
        "app.integrations.tasks.*": {"queue": "notifications"},
    },
)

celery.autodiscover_tasks(["app.ingestion", "app.graph", "app.integrations"])

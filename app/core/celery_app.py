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
        Queue(
            "evaluation",
            routing_key="evaluation",
            queue_arguments={"x-dead-letter-exchange": "dlx",
                             "x-dead-letter-routing-key": "dead.evaluation"},
        ),
        Queue("dead_letter", dead_letter_exchange, routing_key="dead.#"),
    ),
    task_routes={
        "app.ingestion.tasks.*": {"queue": "ingestion"},
        "app.graph.tasks.*": {"queue": "graph"},
        "app.integrations.tasks.*": {"queue": "notifications"},
        "app.evaluation.tasks.*": {"queue": "evaluation"},
    },
)

celery.autodiscover_tasks(["app.ingestion", "app.graph", "app.integrations", "app.evaluation"])

# Worker processes import models through task modules only; FKs reference
# tables by name and fail to resolve unless every model is in Base.metadata.
# The API gets this for free via app.main — the worker needs it explicitly.
from app.documents import models as _documents_models  # noqa: E402, F401
from app.evaluation import models as _evaluation_models  # noqa: E402, F401
from app.tenants import models as _tenants_models  # noqa: E402, F401

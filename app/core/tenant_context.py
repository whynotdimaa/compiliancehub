"""Request-scoped tenant context.

Stored in a ContextVar so it is safe under asyncio concurrency:
each request/task gets its own value, no globals leaking between requests.
"""
import uuid
from contextvars import ContextVar

current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("current_tenant_id", default=None)

"""Slack incoming-webhook notifications.

Fail-safe by design: no webhook configured -> silently skipped; HTTP errors
are logged and swallowed. A monitoring channel being down must never affect
ingestion or evaluation outcomes.
"""
import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


def send_slack_message(text: str) -> bool:
    if not settings.slack_webhook_url:
        return False
    try:
        response = httpx.post(settings.slack_webhook_url, json={"text": text}, timeout=10.0)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("slack_notify_failed", error=str(exc))
        return False

"""Notification tasks (routed to the lightweight `notifications` queue —
they must never wait behind heavy ingestion work, see celery_app.py)."""
from app.core.celery_app import celery
from app.integrations.slack import send_slack_message


@celery.task(name="app.integrations.tasks.notify_slack")
def notify_slack(text: str) -> bool:
    return send_slack_message(text)

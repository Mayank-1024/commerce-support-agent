"""Celery task: a thin wrapper that adds retries and failure handling.

- Transient infrastructure errors (e.g. SQLite busy/locked) -> release the
  claim and retry with backoff, up to max_retries.
- Retries exhausted, or any other exception -> mark the message `failed`
  so it never hangs in `processing`.
Model-side errors never reach here: the agent loop turns them into a
deterministic escalation.
"""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from worker import service
from worker.celery_app import celery_app

TRANSIENT_ERRORS = (OperationalError,)


@celery_app.task(bind=True, name="process_message", max_retries=3)
def process_message_task(self, message_id: str) -> str:
    try:
        return service.process_message(message_id)
    except TRANSIENT_ERRORS as exc:
        service.release(message_id)
        if self.request.retries >= self.max_retries:
            service.mark_failed(message_id, f"retries exhausted: {exc!r}")
            return "failed"
        raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
    except Exception as exc:
        service.mark_failed(message_id, repr(exc))
        return "failed"

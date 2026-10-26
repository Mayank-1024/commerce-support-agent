"""Celery application.

Redis is the broker. With CELERY_TASK_ALWAYS_EAGER=1 tasks run inline in the
calling process, which is how the tests and the no-Redis local demo work.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from observability.logging import configure_logging
from settings import get_settings

_settings = get_settings()

celery_app = Celery("commerce_support_agent", broker=_settings.redis_url,
                    include=["worker.tasks"])
celery_app.conf.update(
    task_always_eager=_settings.celery_always_eager,
    task_ignore_result=True,  # state lives in SQLite, not in a result backend
    task_acks_late=True,  # a worker crash re-delivers the task (idempotency handles it)
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    # A turn spends most of its time waiting on the model API (I/O-bound), so threads
    # fit better than processes. The default prefork pool also fails on macOS, where
    # billiard starts children with "spawn" and the task tracer is never initialized.
    worker_pool="threads",
)


@setup_logging.connect
def _use_json_logging(**_kwargs) -> None:
    """Replace Celery's log format with the same JSON lines the API emits."""
    configure_logging()

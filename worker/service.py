"""Processing one queued shopper message, independent of Celery.

Keeping this out of the task function means it can be unit-tested directly
and the Celery task stays a thin wrapper about retries.

Idempotency: the first thing we do is an atomic "claim" (UPDATE ... WHERE
status='queued'). Only one delivery can win it; a re-delivered task for a
message that is already processing or finished does nothing.

Atomicity: the agent's tool writes (returns, escalations, audit rows), the
reply and the status change commit in ONE transaction. If anything fails
midway, none of it is kept, so a retry starts clean and cannot double-create
a return.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from agent.loop import TurnConfig, run_turn
from agent.model_client import ModelClient
from agent.prompts import wrap_shopper_message
from observability.logging import get_logger, log_event
from settings import Settings, get_settings
from store.catalog import load_catalog
from store.db import session_scope
from store.models import Message, TurnMetric
from tools.handlers import ToolContext
from worker import model_factory

log = get_logger("worker")

ModelFactory = Callable[[Settings, str, bool], ModelClient]


def claim(message_id: str) -> bool:
    with session_scope() as s:
        res = s.execute(update(Message)
                        .where(Message.id == message_id, Message.status == "queued")
                        .values(status="processing"))
        return res.rowcount == 1


def release(message_id: str) -> None:
    """Put a claimed message back to queued so a task retry can claim it again."""
    with session_scope() as s:
        s.execute(update(Message)
                  .where(Message.id == message_id, Message.status == "processing")
                  .values(status="queued"))


def mark_failed(message_id: str, error: str) -> None:
    with session_scope() as s:
        s.execute(update(Message)
                  .where(Message.id == message_id, Message.status.in_(("queued", "processing")))
                  .values(status="failed", error=error[:2000]))
    log_event(log, "message_failed", level=40, message_id=message_id, error=error[:500])


def build_history(s: Session, conversation_id: str, before: Message) -> list[dict[str, Any]]:
    """Earlier turns as plain text (shopper text and the agent's reply text)."""
    rows = s.scalars(select(Message)
                     .where(Message.conversation_id == conversation_id,
                            Message.created_at < before.created_at)
                     .order_by(Message.created_at)).all()
    history: list[dict[str, Any]] = []
    answered = {m.reply_to for m in rows if m.role == "agent"}
    for m in rows:
        if m.role == "shopper" and m.id in answered:
            history.append({"role": "user", "content": wrap_shopper_message(m.text)})
        elif m.role == "agent":
            history.append({"role": "assistant", "content": m.text})
    return history


def process_message(message_id: str, model_factory_fn: ModelFactory | None = None) -> str:
    """Run the agent for one shopper message. Returns the final status or 'skipped'."""
    if not claim(message_id):
        log_event(log, "message_skipped", message_id=message_id, reason="already_claimed")
        return "skipped"

    settings = get_settings()
    factory = model_factory_fn or model_factory.build_model
    with session_scope() as s:
        msg = s.get(Message, message_id)
        assert msg is not None
        history = build_history(s, msg.conversation_id, msg)
        model = factory(settings, msg.text, bool(history))
        ctx = ToolContext(session=s, catalog=load_catalog(settings.data_dir),
                          today=settings.store_today, conversation_id=msg.conversation_id,
                          message_id=msg.id)
        result = run_turn(model, ctx, msg.text, history=history,
                          config=TurnConfig(max_tool_steps=settings.max_tool_steps,
                                            max_model_attempts=settings.model_max_attempts))
        s.add(Message(conversation_id=msg.conversation_id, role="agent",
                      text=result.reply.reply, reply_to=msg.id,
                      reply_json=result.reply.model_dump()))
        msg.status = result.outcome
        st = result.state
        s.add(TurnMetric(message_id=msg.id, conversation_id=msg.conversation_id,
                         model=result.model, outcome=result.outcome,
                         latency_ms=result.latency_ms, model_calls=st.model_calls,
                         tool_calls=st.tool_steps, api_retries=st.api_retries,
                         output_retries=st.output_retries,
                         fallback_reason=result.fallback_reason, escalated=result.reply.escalated,
                         input_tokens=st.input_tokens, output_tokens=st.output_tokens))
        return result.outcome

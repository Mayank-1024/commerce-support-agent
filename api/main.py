"""FastAPI app: accepts shopper messages and hands them to Celery.

The HTTP layer never calls the model. POST /messages stores the message,
enqueues a task and returns 202 immediately; clients poll
GET /conversations/{id} for the reply.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api import metrics
from api.schemas import (
    ConversationCreated,
    ConversationOut,
    MessageAccepted,
    MessageOut,
    PostMessage,
)
from observability.logging import configure_logging, get_logger, log_event
from store.db import get_factory
from store.models import Conversation, Message
from worker.service import mark_failed
from worker.tasks import process_message_task

configure_logging()
log = get_logger("api")
app = FastAPI(title="Commerce Support Agent", version="0.1.0")


def db() -> Iterator[Session]:
    session = get_factory()()
    try:
        yield session
    finally:
        session.close()


DB = Annotated[Session, Depends(db)]


@app.get("/healthz")
def healthz(s: DB) -> dict[str, str]:
    s.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics(s: DB) -> dict:
    return metrics.collect(s)


@app.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(s: DB) -> ConversationCreated:
    conv = Conversation()
    s.add(conv)
    s.commit()
    return ConversationCreated(conversation_id=conv.id)


@app.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def post_message(conversation_id: str, body: PostMessage,
                 s: DB) -> MessageAccepted:
    if s.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    msg = Message(conversation_id=conversation_id, role="shopper", text=body.text,
                  status="queued")
    s.add(msg)
    s.commit()  # commit BEFORE enqueueing so the worker can see the row
    message_id = msg.id
    try:
        process_message_task.delay(message_id)
    except Exception as exc:  # broker down: fail loudly instead of leaving it "queued"
        mark_failed(message_id, f"enqueue failed: {exc!r}")
        raise HTTPException(status_code=503, detail="queue unavailable") from exc
    log_event(log, "message_enqueued", conversation_id=conversation_id, message_id=message_id)
    return MessageAccepted(message_id=message_id, status="queued")


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, s: DB) -> ConversationOut:
    if s.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    rows = s.scalars(select(Message).where(Message.conversation_id == conversation_id)
                     .order_by(Message.created_at)).all()
    out = []
    for m in rows:
        reply = m.reply_json or {}
        out.append(MessageOut(
            id=m.id, role=m.role, text=m.text, status=m.status, reply_to=m.reply_to,
            cited_doc_ids=reply.get("cited_doc_ids", []), actions=reply.get("actions", []),
            escalated=reply.get("escalated") if m.role == "agent" else None,
            created_at=m.created_at))
    shopper = [m for m in rows if m.role == "shopper"]
    return ConversationOut(conversation_id=conversation_id,
                           status=shopper[-1].status if shopper else "open", messages=out)

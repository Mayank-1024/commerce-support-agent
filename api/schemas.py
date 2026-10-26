"""Request and response bodies for the HTTP API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreated(BaseModel):
    conversation_id: str


class PostMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MessageAccepted(BaseModel):
    message_id: str
    status: str


class MessageOut(BaseModel):
    id: str
    role: str
    text: str
    status: str | None
    reply_to: str | None
    cited_doc_ids: list[str] = []
    actions: list[str] = []
    escalated: bool | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    conversation_id: str
    status: str  # status of the latest shopper message, or "open" if none yet
    messages: list[MessageOut]

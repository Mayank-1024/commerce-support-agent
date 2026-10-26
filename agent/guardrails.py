"""Validation of the model's final answer.

A final answer is accepted only if ALL of these hold:
1. it parses as JSON and matches the AgentReply schema;
2. grounding: every cited doc_id was returned by search_help_center this turn;
3. honesty about actions: every claimed action was actually performed by a tool;
4. `escalated` is true exactly when an escalation was actually created.

Anything else raises ReplyValidationError, whose message is fed back to the
model for one retry (see agent/loop.py).
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from agent.reply import AgentReply
from agent.state import TurnState


class ReplyValidationError(Exception):
    pass


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def parse_reply(text: str) -> AgentReply:
    try:
        data = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        raise ReplyValidationError(f"Final answer is not valid JSON ({exc.msg}).") from exc
    try:
        return AgentReply.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}"
                             for e in exc.errors(include_url=False))
        raise ReplyValidationError(f"Final answer does not match the schema: {problems}") from exc


def check_grounding(reply: AgentReply, state: TurnState) -> None:
    ungrounded = [d for d in reply.cited_doc_ids if d not in state.retrieved_doc_ids]
    if ungrounded:
        raise ReplyValidationError(
            f"cited_doc_ids {ungrounded} were not returned by search_help_center in this turn "
            f"(retrieved: {sorted(state.retrieved_doc_ids)}).")


def check_actions(reply: AgentReply, state: TurnState) -> None:
    invented = [a for a in reply.actions if a not in state.performed_actions]
    if invented:
        raise ReplyValidationError(
            f"actions {invented} were not performed by any tool "
            f"(performed: {state.performed_actions}).")
    if reply.escalated != state.escalated:
        raise ReplyValidationError(
            f"escalated={reply.escalated} but escalate_to_human "
            f"{'was' if state.escalated else 'was not'} called.")


def validate_reply(text: str, state: TurnState) -> AgentReply:
    reply = parse_reply(text)
    check_grounding(reply, state)
    check_actions(reply, state)
    # The model may omit actions but never add them; the persisted record is
    # the server's list, so nothing a tool did is hidden from the transcript.
    return reply.model_copy(update={"actions": list(state.performed_actions)})

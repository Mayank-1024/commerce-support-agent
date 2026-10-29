"""Validation of the model's final answer.

A final answer is accepted only if ALL of these hold:
1. it parses as JSON and matches the AgentReply schema;
2. grounding: every cited doc_id was returned by search_help_center this turn;
3. honesty about actions: every claimed action was actually performed by a tool;
4. `escalated` is true exactly when an escalation was actually created;
5. the reply text never tells the shopper it was handed to a human unless an
   escalation was actually created (found by the first real-model eval,
   2026-10-28: the model wrote "I've passed this to a specialist" with
   escalated=false and no tool call).

Anything else raises ReplyValidationError, whose message is fed back to the
model for one retry (see agent/loop.py).
"""

from __future__ import annotations

import json
import re

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


_HUMAN = (r"(?:a|an|our|the)\s+(?:support\s+|billing\s+)?"
          r"(?:human|person|specialist|agent|representative|team\s+member|team"
          r"|member\s+of\s+(?:our|the)\s+(?:support\s+)?team)")
_DONE_VERBS = (r"(?:passed|passing|handed|handing|forwarded|forwarding|referred|referring"
               r"|routed|routing|sent|sending|connected|connecting)")
_PROMISE_VERBS = r"(?:pass|hand|forward|refer|route|send|connect|escalate|transfer)"
_FOLLOW_UP = r"(?:follow\s+up|reach\s+out|get\s+back\s+to\s+you|be\s+in\s+touch|contact\s+you)"
_HANDOFF_CLAIMS = [re.compile(p, re.I) for p in (
    r"\b(?:i|we)(?:'ve|\s+have|\s+had)?\s+(?:just\s+|now\s+)?(?:escalated|transferred)\b",
    r"\b(?:been|being)\s+(?:escalated|transferred)\b",
    r"\b(?:i'm|i\s+am|we're|we\s+are)\s+(?:now\s+)?(?:escalating|transferring)\b",
    r"\b" + _DONE_VERBS + r"\b[^.?!]{0,40}?\b(?:to|with)\s+" + _HUMAN,
    r"\b(?:i'll|i\s+will|we'll|we\s+will)\s+(?:now\s+)?" + _PROMISE_VERBS + r"\b",
    _HUMAN + r"\s+will\s+" + _FOLLOW_UP,
    r"\bESC-\d+\b",
)]
# Sentences where the agent only offers a handoff ("I can escalate this") are not claims that one
# happened; "a specialist who can review it" is not an offer. A false positive is safe: the model
# retries, and if it still fails the loop falls back to a real escalation.
_OFFER = re.compile(
    r"\b(?:(?:i|we)\s+(?:can|could)(?!'t|not|n't)|would\s+you\s+like|do\s+you\s+want|want\s+me\s+to|shall\s+i"
    r"|if\s+you(?:'d)?\s+like|happy\s+to|i'd\s+be\s+glad|let\s+me\s+know\s+if"
    r"|if\s+you\s+(?:ask|want|need|prefer))\b", re.I)


def handoff_claim(text: str) -> str | None:
    """The first sentence that tells the shopper a human now has their request, if any."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if _OFFER.search(sentence):
            continue
        if any(p.search(sentence) for p in _HANDOFF_CLAIMS):
            return sentence.strip()
    return None


def check_handoff_claim(reply: AgentReply, state: TurnState) -> None:
    if state.escalated:
        return
    claim = handoff_claim(reply.reply)
    if claim:
        raise ReplyValidationError(
            f"the reply tells the shopper a human has their request ({claim!r}) but "
            f"escalate_to_human was not called. Call escalate_to_human first, "
            f"or do not claim a handoff.")


def validate_reply(text: str, state: TurnState) -> AgentReply:
    reply = parse_reply(text)
    check_grounding(reply, state)
    check_actions(reply, state)
    check_handoff_claim(reply, state)
    # The model may omit actions but never add them; the persisted record is
    # the server's list, so nothing a tool did is hidden from the transcript.
    return reply.model_copy(update={"actions": list(state.performed_actions)})

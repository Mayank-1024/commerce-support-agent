"""The deterministic fallback: escalate to a human with a safe holding reply.

Used whenever the agent cannot produce a trustworthy answer: output still
invalid after one retry, tool-step limit hit, model unavailable after retries,
or a non-retryable model error. No model call is involved, so this path
cannot itself fail in a model-shaped way.
"""

from __future__ import annotations

from agent.reply import AgentReply
from agent.state import TurnState
from tools.handlers import ToolContext, create_escalation

HOLDING_REPLY = (
    "Thanks for your patience. I wasn't able to finish this request automatically, so I've "
    "passed your conversation to our support team. A specialist will follow up by email "
    "within one business day."
)


def fallback_reply(ctx: ToolContext, state: TurnState, reason: str,
                   shopper_text: str) -> AgentReply:
    if not state.escalated:  # do not double-escalate if the model already did
        summary = (f"Automatic escalation ({reason}). Shopper wrote: {shopper_text[:500]!r}. "
                   f"Tools called this turn: {state.tools_called or 'none'}. "
                   f"Actions performed: {state.performed_actions or 'none'}.")
        esc = create_escalation(ctx, reason=reason, summary=summary, source="fallback")
        state.performed_actions.append(f"escalation_created:{esc.public_id}")
    return AgentReply(reply=HOLDING_REPLY, cited_doc_ids=[],
                      actions=list(state.performed_actions), escalated=True)

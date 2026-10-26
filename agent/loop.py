"""The agent loop for one shopper message ("turn").

    shopper text -> model -> (tool calls -> tool results -> model)* -> final JSON
                                                                     |
                                       guardrails: schema, grounding, actions
                                                                     |
                                       valid? done : one retry : fallback escalate

Limits: at most `max_tool_steps` tool calls per turn; each model call is
retried with exponential backoff on transient errors; one corrective retry
for an invalid final answer. Every failure path ends in the same
deterministic fallback, so a turn always finishes with a safe reply.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.fallback import fallback_reply
from agent.guardrails import ReplyValidationError, validate_reply
from agent.model_client import ModelClient, ModelError, ModelTurn, TransientModelError
from agent.prompts import SYSTEM_PROMPT, validation_retry_message, wrap_shopper_message
from agent.reply import AgentReply
from agent.retry import call_with_retries
from agent.state import TurnState
from observability.logging import get_logger, log_event
from tools import registry
from tools.handlers import ToolContext

log = get_logger("agent")


@dataclass
class TurnConfig:
    max_tool_steps: int = 6
    max_model_attempts: int = 3  # per model call, including the first


@dataclass
class TurnResult:
    reply: AgentReply
    state: TurnState
    fallback_reason: str | None
    latency_ms: float
    model: str

    @property
    def outcome(self) -> str:
        return "escalated" if self.reply.escalated else "done"


def run_turn(model: ModelClient, ctx: ToolContext, shopper_text: str,
             history: list[dict[str, Any]] | None = None, config: TurnConfig | None = None,
             sleep: Callable[[float], None] = time.sleep) -> TurnResult:
    config = config or TurnConfig()
    start = time.perf_counter()
    state = TurnState()
    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": wrap_shopper_message(shopper_text)})
    tools = registry.tool_definitions()

    def finish(reply: AgentReply, fallback_reason: str | None) -> TurnResult:
        result = TurnResult(reply, state, fallback_reason,
                            round((time.perf_counter() - start) * 1000, 2), model.name)
        log_event(log, "turn_completed", conversation_id=ctx.conversation_id,
                  message_id=ctx.message_id, model=model.name, outcome=result.outcome,
                  latency_ms=result.latency_ms, tool_calls=state.tool_steps,
                  model_calls=state.model_calls, api_retries=state.api_retries,
                  output_retries=state.output_retries, fallback_reason=fallback_reason,
                  input_tokens=state.input_tokens, output_tokens=state.output_tokens)
        return result

    def fallback(reason: str) -> TurnResult:
        return finish(fallback_reply(ctx, state, reason, shopper_text), reason)

    while True:
        try:
            turn = _call_model(model, messages, tools, state, ctx, config, sleep)
        except TransientModelError:
            return fallback("model_unavailable")
        except ModelError:
            return fallback("model_error")

        messages.append({"role": "assistant", "content": turn.assistant_content})

        if turn.tool_calls:
            if state.tool_steps + len(turn.tool_calls) > config.max_tool_steps:
                return fallback("step_limit")
            results = []
            for call in turn.tool_calls:
                state.tool_steps += 1
                executed = registry.execute(ctx, call.name, call.input, step=state.tool_steps)
                state.tools_called.append(call.name)
                if executed.result.action:
                    state.performed_actions.append(executed.result.action)
                state.retrieved_doc_ids.update(executed.result.doc_ids)
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": executed.content(), "is_error": executed.is_error})
            # all results for one assistant message go back in a single user message
            messages.append({"role": "user", "content": results})
            continue

        try:
            return finish(validate_reply(turn.text, state), None)
        except ReplyValidationError as err:
            log_event(log, "reply_rejected", conversation_id=ctx.conversation_id,
                      message_id=ctx.message_id, error=str(err),
                      retry=state.output_retries == 0)
            if state.output_retries >= 1:
                return fallback("invalid_output")
            state.output_retries += 1
            messages.append({"role": "user", "content": validation_retry_message(str(err))})


def _call_model(model: ModelClient, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                state: TurnState, ctx: ToolContext, config: TurnConfig,
                sleep: Callable[[float], None]) -> ModelTurn:
    step = state.model_calls + 1

    def attempt() -> ModelTurn:
        t0 = time.perf_counter()
        try:
            turn = model.complete(system=SYSTEM_PROMPT, messages=messages, tools=tools)
        except ModelError as exc:
            log_event(log, "model_call", conversation_id=ctx.conversation_id,
                      message_id=ctx.message_id, step=step, model=model.name,
                      latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                      outcome="transient_error" if isinstance(exc, TransientModelError)
                      else "error", error=str(exc))
            raise
        log_event(log, "model_call", conversation_id=ctx.conversation_id,
                  message_id=ctx.message_id, step=step, model=model.name,
                  latency_ms=round((time.perf_counter() - t0) * 1000, 2), outcome="ok",
                  stop_reason=turn.stop_reason, tool_calls=[c.name for c in turn.tool_calls])
        return turn

    def on_retry(_attempt: int, _exc: Exception, _delay: float) -> None:
        state.api_retries += 1

    turn = call_with_retries(attempt, max_attempts=config.max_model_attempts, sleep=sleep,
                             on_retry=on_retry)
    state.model_calls += 1
    state.add_usage(turn.input_tokens, turn.output_tokens)
    return turn

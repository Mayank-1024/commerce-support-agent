"""Tool registry: definitions sent to Claude, plus validated dispatch.

`execute()` is the single choke point for tool calls. It validates the
model's arguments against the Pydantic schema, runs the handler, times it,
writes the audit row, and emits a structured log line. Anything that goes
wrong comes back to the model as an `is_error` result instead of crashing
the turn.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from observability.logging import get_logger, log_event
from store.models import ToolCallLog
from tools import handlers
from tools.handlers import ToolContext, ToolResult
from tools.schemas import (
    EscalateToHumanInput,
    LookupOrderInput,
    RequestReturnInput,
    SearchHelpCenterInput,
    SearchProductsInput,
)

log = get_logger("tools")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], ToolResult]

    def definition(self) -> dict[str, Any]:
        """The tool definition in the shape the Messages API expects."""
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_model.model_json_schema()}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("lookup_order",
         "Look up an order's status and items. Requires the order number AND the email used "
         "at checkout; returns verified=false if they do not match.",
         LookupOrderInput, handlers.lookup_order),
    Tool("search_products",
         "Search the store's product catalog by keywords. Returns matching products with "
         "price, attributes, and whether they are final sale.",
         SearchProductsInput, handlers.search_products),
    Tool("search_help_center",
         "Search help-center articles (shipping, returns, exchanges, tracking, payment, "
         "sizing, warranty, contact). Returns passages with a doc_id to cite.",
         SearchHelpCenterInput, handlers.search_help_center),
    Tool("request_return",
         "Start a return for one item. Requires order number, checkout email, item SKU and "
         "reason. The store's rules decide eligibility; the result says created=true with a "
         "return_id, or created=false with the reason.",
         RequestReturnInput, handlers.request_return),
    Tool("escalate_to_human",
         "Hand the conversation to a human support specialist. Use when the shopper asks for "
         "a person, for billing disputes, warranty claims, or anything you cannot resolve.",
         EscalateToHumanInput, handlers.escalate_to_human),
]}


def tool_definitions() -> list[dict[str, Any]]:
    return [t.definition() for t in TOOLS.values()]


@dataclass
class ExecutedCall:
    """What the agent loop needs back from one tool call."""
    tool: str
    result: ToolResult
    is_error: bool

    def content(self) -> str:
        return json.dumps(self.result.data)


def execute(ctx: ToolContext, name: str, raw_input: dict[str, Any], step: int) -> ExecutedCall:
    start = time.perf_counter()
    tool = TOOLS.get(name)
    is_error = False
    if tool is None:
        result, is_error = ToolResult({"error": f"Unknown tool '{name}'."}, "unknown_tool"), True
    else:
        try:
            args = tool.input_model.model_validate(raw_input)
            result = tool.handler(ctx, args)
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_input=False)
            result = ToolResult({"error": "Invalid arguments.", "details": errors},
                                "invalid_input")
            is_error = True
        except Exception as exc:  # a bug in a handler must not take down the turn
            log_event(log, "tool_error", level=40, tool=name, error=repr(exc))
            result = ToolResult({"error": "The tool failed. Try again or escalate."}, "error")
            is_error = True
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    ctx.session.add(ToolCallLog(
        conversation_id=ctx.conversation_id, message_id=ctx.message_id, step=step, tool=name,
        input_json=raw_input, output_json=result.data, outcome=result.outcome,
        latency_ms=latency_ms))
    log_event(log, "tool_call", conversation_id=ctx.conversation_id,
              message_id=ctx.message_id, step=step, tool=name, latency_ms=latency_ms,
              outcome=result.outcome)
    return ExecutedCall(name, result, is_error)

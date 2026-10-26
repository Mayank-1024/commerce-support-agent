"""A fake model that replays a fixed script, for tests and offline evals.

Each script step is one model response. A step is a dict with one of:

    {"tool_calls": [{"name": "lookup_order", "input": {...}}, ...]}
    {"final": {"reply": ..., "cited_doc_ids": [...], "actions": [...], "escalated": false}}
    {"final_raw": "any text, e.g. invalid JSON"}
    {"error": "transient"}   # raises TransientModelError
    {"error": "fatal"}       # raises ModelError

The script is the model's side of the conversation only. Tools still run
for real against the database, and every guardrail still applies, so a
script that "misbehaves" (claims a return it never made, cites a doc it
never retrieved) exercises exactly the code path a misbehaving real model
would.
"""

from __future__ import annotations

import json
from typing import Any

from agent.model_client import ModelError, ModelTurn, ToolCall, TransientModelError


class ScriptedModel:
    name = "scripted"

    def __init__(self, steps: list[dict[str, Any]]):
        self.steps = list(steps)
        self.calls = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    def complete(self, *, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> ModelTurn:
        self.seen_messages.append(list(messages))
        if self.calls >= len(self.steps):
            raise ModelError("script exhausted")
        step = self.steps[self.calls]
        self.calls += 1

        if "error" in step:
            if step["error"] == "transient":
                raise TransientModelError("scripted transient error")
            raise ModelError("scripted fatal error")

        if "tool_calls" in step:
            calls = [ToolCall(id=f"toolu_{self.calls}_{i}", name=c["name"], input=c["input"])
                     for i, c in enumerate(step["tool_calls"])]
            content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                       for c in calls]
            return ModelTurn(content, calls, text="", stop_reason="tool_use")

        text = step["final_raw"] if "final_raw" in step else json.dumps(step["final"])
        return ModelTurn([{"type": "text", "text": text}], [], text=text, stop_reason="end_turn")

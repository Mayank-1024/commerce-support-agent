"""ModelClient backed by the Claude Messages API (anthropic SDK 2.x).

Design notes:
- The SDK's own retries are turned off (max_retries=0) because the agent loop
  owns retry policy; otherwise retries would multiply.
- Each request has a per-call timeout.
- SDK errors are mapped into two buckets: TransientModelError (retry) and
  ModelError (give up and fall back). The except chain goes most-specific first.
- The final answer is constrained with structured outputs
  (`output_config.format`) and is *still* validated by our own guardrails,
  because a schema cannot check grounding or whether actions really happened.
- `response.content` is passed back verbatim (including any thinking blocks).
"""

from __future__ import annotations

from typing import Any

import anthropic

from agent.model_client import ModelError, ModelTurn, ToolCall, TransientModelError
from agent.reply import reply_json_schema


class AnthropicModel:
    def __init__(self, model: str, *, effort: str = "medium", max_tokens: int = 16000,
                 timeout_s: float = 30.0, client: Any | None = None):
        self.name = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client or anthropic.Anthropic(max_retries=0, timeout=timeout_s)

    def complete(self, *, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> ModelTurn:
        try:
            response = self._client.messages.create(
                model=self.name,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": reply_json_schema()},
                },
            )
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise TransientModelError(f"connection/timeout: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise TransientModelError("rate limited") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:  # InternalServerError, OverloadedError (529)
                raise TransientModelError(f"server error {exc.status_code}") from exc
            raise ModelError(f"API error {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            raise ModelError("model refused the request")

        tool_calls = [ToolCall(id=b.id, name=b.name, input=dict(b.input))
                      for b in response.content if b.type == "tool_use"]
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = response.usage
        return ModelTurn(
            assistant_content=list(response.content),
            tool_calls=tool_calls,
            text=text,
            stop_reason=response.stop_reason or "",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

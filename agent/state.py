"""Per-turn bookkeeping that the guardrails check the model's claims against."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnState:
    performed_actions: list[str] = field(default_factory=list)  # from tools, never the model
    retrieved_doc_ids: set[str] = field(default_factory=set)  # from search_help_center
    tools_called: list[str] = field(default_factory=list)
    tool_steps: int = 0
    model_calls: int = 0
    api_retries: int = 0
    output_retries: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def escalated(self) -> bool:
        return any(a.startswith("escalation_created:") for a in self.performed_actions)

    def add_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + input_tokens
        if output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + output_tokens

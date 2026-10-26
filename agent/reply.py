"""The structured final answer every turn must produce."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=4000,
                       description="The message shown to the shopper.")
    cited_doc_ids: list[str] = Field(
        description="doc_id of every help-center article the reply relies on.")
    actions: list[str] = Field(
        description="Action strings returned by tools in this turn, copied exactly "
                    "(e.g. 'return_created:RET-00001'). Empty if nothing was done.")
    escalated: bool = Field(description="True only if escalate_to_human was called.")


def reply_json_schema() -> dict:
    """JSON Schema for structured outputs (`output_config.format`)."""
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "cited_doc_ids": {"type": "array", "items": {"type": "string"}},
            "actions": {"type": "array", "items": {"type": "string"}},
            "escalated": {"type": "boolean"},
        },
        "required": ["reply", "cited_doc_ids", "actions", "escalated"],
        "additionalProperties": False,
    }

"""Pydantic input schemas for each tool.

These serve two purposes: they generate the JSON Schema that Claude sees in
the tool definition, and they validate whatever arguments the model sends
back before any handler runs. `extra="forbid"` means the model cannot smuggle
in extra arguments (there is no "override" or "force" field to find).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookupOrderInput(_Strict):
    order_id: str = Field(description="Order number, e.g. ORD-10001", max_length=32)
    email: str = Field(description="Email address used at checkout", max_length=254)


class SearchProductsInput(_Strict):
    query: str = Field(description="What the shopper is looking for", max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)


class SearchHelpCenterInput(_Strict):
    query: str = Field(description="Policy or how-to question to look up", max_length=300)


class RequestReturnInput(_Strict):
    order_id: str = Field(max_length=32)
    email: str = Field(description="Email address used at checkout", max_length=254)
    item_sku: str = Field(description="SKU of the item to return, e.g. SKU-1001", max_length=32)
    reason: str = Field(description="Shopper's reason for the return", max_length=500)


class EscalateToHumanInput(_Strict):
    reason: str = Field(description="Why a person needs to take over", max_length=300)
    summary: str = Field(description="Short summary of the conversation so far", max_length=2000)

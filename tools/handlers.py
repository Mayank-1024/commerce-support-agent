"""Tool implementations: plain functions over the catalog and the database.

Every handler takes a ToolContext and a validated input model and returns a
ToolResult. A handler that changes state reports it in `ToolResult.action`;
those strings are the only source of truth for what the agent "did".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from store.catalog import Catalog, Order
from store.eligibility import check_return_eligibility
from store.models import Escalation, ReturnRequest
from tools.schemas import (
    EscalateToHumanInput,
    LookupOrderInput,
    RequestReturnInput,
    SearchHelpCenterInput,
    SearchProductsInput,
)

# Same message whether the order does not exist or the email is wrong, so a
# caller cannot probe which order numbers are real.
NOT_VERIFIED = {
    "verified": False,
    "message": "We couldn't verify an order with that order number and email address.",
}


@dataclass
class ToolContext:
    session: Session
    catalog: Catalog
    today: date
    conversation_id: str | None = None
    message_id: str | None = None


@dataclass
class ToolResult:
    data: dict[str, Any]
    outcome: str = "ok"
    action: str | None = None  # e.g. "return_created:RET-00001"
    doc_ids: list[str] = field(default_factory=list)  # help-center docs surfaced


def _verify(ctx: ToolContext, order_id: str, email: str) -> Order | None:
    order = ctx.catalog.orders.get(order_id.strip().upper())
    if order is None or order.email.lower() != email.strip().lower():
        return None
    return order


def lookup_order(ctx: ToolContext, args: LookupOrderInput) -> ToolResult:
    order = _verify(ctx, args.order_id, args.email)
    if order is None:
        return ToolResult(NOT_VERIFIED, outcome="not_verified")
    return ToolResult({
        "verified": True,
        "order_id": order.order_id,
        "status": order.status,
        "order_date": order.order_date.isoformat(),
        "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
        "tracking_number": order.tracking_number,
        "items": [i.model_dump() for i in order.items],
    })


def search_products(ctx: ToolContext, args: SearchProductsInput) -> ToolResult:
    hits = ctx.catalog.search_products(args.query, args.max_results)
    return ToolResult({"results": [p.model_dump() for p in hits]},
                      outcome="ok" if hits else "no_results")


def search_help_center(ctx: ToolContext, args: SearchHelpCenterInput) -> ToolResult:
    hits = ctx.catalog.search_help(args.query, k=3)
    results = [{"doc_id": c.doc_id, "title": c.title, "section": c.section, "text": c.text}
               for c in hits]
    return ToolResult({"results": results}, outcome="ok" if hits else "no_results",
                      doc_ids=sorted({c.doc_id for c in hits}))


def request_return(ctx: ToolContext, args: RequestReturnInput) -> ToolResult:
    order = _verify(ctx, args.order_id, args.email)
    if order is None:
        return ToolResult(NOT_VERIFIED, outcome="not_verified")
    returned = set(ctx.session.scalars(
        select(ReturnRequest.sku).where(ReturnRequest.order_id == order.order_id)))
    sku = args.item_sku.strip().upper()
    verdict = check_return_eligibility(order, sku, ctx.today, returned)
    if not verdict.eligible:
        return ToolResult({"created": False, "reason_code": verdict.reason_code,
                           "detail": verdict.detail},
                          outcome=f"ineligible:{verdict.reason_code}")
    ret = ReturnRequest(order_id=order.order_id, sku=sku, reason=args.reason,
                        conversation_id=ctx.conversation_id)
    ctx.session.add(ret)
    ctx.session.flush()  # assigns ret.id
    return ToolResult(
        {"created": True, "return_id": ret.public_id, "detail": verdict.detail,
         "next_step": "A prepaid return label will be emailed to the shopper."},
        outcome="return_created", action=f"return_created:{ret.public_id}")


def create_escalation(ctx: ToolContext, reason: str, summary: str, source: str) -> Escalation:
    esc = Escalation(conversation_id=ctx.conversation_id, reason=reason, summary=summary,
                     source=source)
    ctx.session.add(esc)
    ctx.session.flush()
    return esc


def escalate_to_human(ctx: ToolContext, args: EscalateToHumanInput) -> ToolResult:
    esc = create_escalation(ctx, args.reason, args.summary, source="model")
    return ToolResult(
        {"escalation_id": esc.public_id,
         "message": "A support specialist will follow up by email within one business day."},
        outcome="escalation_created", action=f"escalation_created:{esc.public_id}")

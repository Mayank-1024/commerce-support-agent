"""Deterministic return-eligibility rules.

This is plain code on purpose: whether a return is allowed is a business
rule, not a judgment call, so the model never decides it. The model can only
*ask* (via the request_return tool); this function answers.

Checks run in a fixed order and the first failure wins, so the reason a
shopper hears is stable and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from store.catalog import Order

RETURN_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason_code: str  # "eligible" or why not
    detail: str
    days_since_delivery: int | None = None


def check_return_eligibility(order: Order, sku: str, today: date,
                             already_returned_skus: set[str]) -> Eligibility:
    item = order.item(sku)
    if item is None:
        return Eligibility(False, "item_not_in_order", "That item is not part of this order.")
    if order.status == "cancelled":
        return Eligibility(False, "order_cancelled", "This order was cancelled, so there is "
                           "nothing to return.")
    if order.delivered_date is None or order.delivered_date > today:
        return Eligibility(False, "not_delivered", "Returns can only be started after the order "
                           "has been delivered.")
    if sku in already_returned_skus:
        return Eligibility(False, "already_returned", "A return already exists for this item.")
    if item.final_sale:
        return Eligibility(False, "final_sale", "This item was sold as final sale and cannot be "
                           "returned.")
    days = (today - order.delivered_date).days
    if days > RETURN_WINDOW_DAYS:
        return Eligibility(False, "outside_window", f"The item was delivered {days} days ago; "
                           f"the return window is {RETURN_WINDOW_DAYS} days.", days)
    return Eligibility(True, "eligible", f"Delivered {days} days ago, within the "
                       f"{RETURN_WINDOW_DAYS}-day window.", days)

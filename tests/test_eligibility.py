from datetime import date, timedelta

import pytest

from store.catalog import Order, OrderItem
from store.eligibility import RETURN_WINDOW_DAYS, check_return_eligibility

TODAY = date(2026, 10, 15)


def order(delivered_days_ago: int | None, final_sale: bool = False,
          status: str = "delivered") -> Order:
    delivered = TODAY - timedelta(days=delivered_days_ago) if delivered_days_ago is not None \
        else None
    return Order(order_id="ORD-1", email="a@example.com", status=status,
                 order_date=TODAY - timedelta(days=40), delivered_date=delivered,
                 tracking_number=None,
                 items=[OrderItem(sku="SKU-1", name="Thing", quantity=1, unit_price=10.0,
                                  final_sale=final_sale)])


@pytest.mark.parametrize("days, eligible", [(0, True), (1, True), (29, True),
                                            (RETURN_WINDOW_DAYS, True),
                                            (RETURN_WINDOW_DAYS + 1, False), (90, False)])
def test_window_boundaries(days, eligible):
    result = check_return_eligibility(order(days), "SKU-1", TODAY, set())
    assert result.eligible is eligible
    assert result.reason_code == ("eligible" if eligible else "outside_window")
    assert result.days_since_delivery == days


def test_not_delivered():
    r = check_return_eligibility(order(None, status="shipped"), "SKU-1", TODAY, set())
    assert (r.eligible, r.reason_code) == (False, "not_delivered")


def test_delivery_date_in_future_counts_as_not_delivered():
    r = check_return_eligibility(order(-2), "SKU-1", TODAY, set())
    assert r.reason_code == "not_delivered"


def test_final_sale_rejected_even_inside_window():
    r = check_return_eligibility(order(1, final_sale=True), "SKU-1", TODAY, set())
    assert (r.eligible, r.reason_code) == (False, "final_sale")


def test_already_returned():
    r = check_return_eligibility(order(3), "SKU-1", TODAY, {"SKU-1"})
    assert (r.eligible, r.reason_code) == (False, "already_returned")


def test_item_not_in_order():
    r = check_return_eligibility(order(3), "SKU-999", TODAY, set())
    assert r.reason_code == "item_not_in_order"


def test_cancelled_order():
    r = check_return_eligibility(order(None, status="cancelled"), "SKU-1", TODAY, set())
    assert r.reason_code == "order_cancelled"


def test_check_order_is_stable():
    # final sale AND outside window: the earlier check (final_sale) wins
    r = check_return_eligibility(order(60, final_sale=True), "SKU-1", TODAY, set())
    assert r.reason_code == "final_sale"

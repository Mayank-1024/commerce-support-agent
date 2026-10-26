from sqlalchemy import func, select

from store.models import Escalation, ReturnRequest, ToolCallLog
from tools import registry
from tools.handlers import NOT_VERIFIED


def run(ctx, name, **kwargs):
    return registry.execute(ctx, name, kwargs, step=1)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_lookup_order_verified(ctx):
    r = run(ctx, "lookup_order", order_id="ORD-10004", email="casey.tanaka@example.com")
    assert r.result.outcome == "ok" and not r.is_error
    assert r.result.data["status"] == "shipped"
    assert r.result.data["tracking_number"] == "TRK10004US"


def test_lookup_order_email_is_case_and_space_insensitive(ctx):
    r = run(ctx, "lookup_order", order_id="ord-10004", email="  Casey.Tanaka@Example.com ")
    assert r.result.data["verified"] is True


def test_lookup_order_wrong_email_does_not_leak(ctx):
    wrong_email = run(ctx, "lookup_order", order_id="ORD-10001", email="x@example.com")
    unknown_order = run(ctx, "lookup_order", order_id="ORD-99999", email="x@example.com")
    # Identical responses: a caller cannot tell a real order from a fake one.
    assert wrong_email.result.data == unknown_order.result.data == NOT_VERIFIED
    assert wrong_email.content() == unknown_order.content()
    assert "Rain Shell" not in wrong_email.content()


def test_search_products(ctx):
    r = run(ctx, "search_products", query="cast iron pan", max_results=2)
    assert r.result.data["results"][0]["sku"] == "SKU-1013"
    assert run(ctx, "search_products", query="unicorn costume").result.outcome == "no_results"


def test_search_products_rejects_out_of_range_max_results(ctx):
    r = run(ctx, "search_products", query="tent", max_results=50)
    assert r.is_error and r.result.outcome == "invalid_input"


def test_search_help_center_reports_doc_ids(ctx):
    r = run(ctx, "search_help_center", query="standard shipping cost")
    assert "shipping" in r.result.doc_ids
    assert all({"doc_id", "title", "section", "text"} <= set(x) for x in r.result.data["results"])


def test_request_return_eligible_creates_record(ctx, session):
    r = run(ctx, "request_return", order_id="ORD-10001", email="avery.okafor@example.com",
            item_sku="SKU-1001", reason="too big")
    assert r.result.outcome == "return_created"
    assert r.result.action == "return_created:RET-00001"
    assert count(session, ReturnRequest) == 1


def test_request_return_twice_is_already_returned(ctx, session):
    args = dict(order_id="ORD-10001", email="avery.okafor@example.com", item_sku="SKU-1001",
                reason="too big")
    run(ctx, "request_return", **args)
    second = run(ctx, "request_return", **args)
    assert second.result.outcome == "ineligible:already_returned"
    assert second.result.action is None
    assert count(session, ReturnRequest) == 1


def test_request_return_ineligible_creates_nothing(ctx, session):
    final_sale = run(ctx, "request_return", order_id="ORD-10003",
                     email="riley.moreau@example.com", item_sku="SKU-1012", reason="x")
    past_window = run(ctx, "request_return", order_id="ORD-10007",
                      email="rowan.haddad@example.com", item_sku="SKU-1018", reason="x")
    assert final_sale.result.outcome == "ineligible:final_sale"
    assert past_window.result.outcome == "ineligible:outside_window"
    assert count(session, ReturnRequest) == 0


def test_request_return_last_day_of_window_is_eligible(ctx):
    r = run(ctx, "request_return", order_id="ORD-10006", email="quinn.novak@example.com",
            item_sku="SKU-1006", reason="x")
    assert r.result.outcome == "return_created"


def test_request_return_wrong_email_is_generic_and_creates_nothing(ctx, session):
    r = run(ctx, "request_return", order_id="ORD-10001", email="attacker@example.com",
            item_sku="SKU-1001", reason="x")
    assert r.result.data == NOT_VERIFIED
    assert count(session, ReturnRequest) == 0


def test_request_return_has_no_override_argument(ctx, session):
    r = run(ctx, "request_return", order_id="ORD-10003", email="riley.moreau@example.com",
            item_sku="SKU-1012", reason="x", override=True)
    assert r.is_error and r.result.outcome == "invalid_input"
    assert count(session, ReturnRequest) == 0


def test_escalate_to_human_creates_record(ctx, session):
    r = run(ctx, "escalate_to_human", reason="billing", summary="disputed charge")
    assert r.result.action == "escalation_created:ESC-00001"
    esc = session.scalars(select(Escalation)).one()
    assert (esc.summary, esc.source) == ("disputed charge", "model")


def test_unknown_tool_is_error(ctx):
    r = run(ctx, "delete_database")
    assert r.is_error and r.result.outcome == "unknown_tool"


def test_every_call_is_audited(ctx, session):
    run(ctx, "lookup_order", order_id="ORD-10001", email="x@example.com")
    run(ctx, "search_products", query="tent")
    rows = session.scalars(select(ToolCallLog).order_by(ToolCallLog.id)).all()
    assert [(r.tool, r.outcome) for r in rows] == [("lookup_order", "not_verified"),
                                                   ("search_products", "ok")]
    assert all(r.conversation_id == "conv-test" and r.latency_ms >= 0 for r in rows)


def test_tool_definitions_have_schemas():
    defs = {d["name"]: d for d in registry.tool_definitions()}
    assert set(defs) == {"lookup_order", "search_products", "search_help_center",
                         "request_return", "escalate_to_human"}
    schema = defs["request_return"]["input_schema"]
    assert set(schema["required"]) == {"order_id", "email", "item_sku", "reason"}
    assert schema["additionalProperties"] is False

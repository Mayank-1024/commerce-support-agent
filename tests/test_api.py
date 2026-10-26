"""End-to-end API tests with Celery in eager mode (no Redis needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from agent.scripted_model import ScriptedModel
from store import db
from worker import service
from worker.celery_app import celery_app
from worker.tasks import process_message_task

STATUS_MSG = "Hi, where is my order ORD-10004? My email is casey.tanaka@example.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    db.configure(url)
    celery_app.conf.task_always_eager = True
    from api.main import app

    with TestClient(app) as c:
        yield c
    celery_app.conf.task_always_eager = False


def new_conversation(client) -> str:
    r = client.post("/conversations")
    assert r.status_code == 201
    return r.json()["conversation_id"]


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_message_flow_202_then_done(client):
    cid = new_conversation(client)
    r = client.post(f"/conversations/{cid}/messages", json={"text": STATUS_MSG})
    assert r.status_code == 202
    message_id = r.json()["message_id"]

    convo = client.get(f"/conversations/{cid}").json()
    assert convo["status"] == "done"
    shopper, agent = convo["messages"]
    assert (shopper["id"], shopper["status"]) == (message_id, "done")
    assert agent["role"] == "agent" and agent["reply_to"] == message_id
    assert "TRK10004US" in agent["text"]
    assert agent["escalated"] is False


def test_unknown_conversation_404(client):
    assert client.get("/conversations/nope").status_code == 404
    assert client.post("/conversations/nope/messages", json={"text": "hi"}).status_code == 404


def test_empty_message_rejected(client):
    cid = new_conversation(client)
    assert client.post(f"/conversations/{cid}/messages", json={"text": ""}).status_code == 422


def test_escalated_status(client, monkeypatch):
    monkeypatch.setattr(service.model_factory, "build_model",
                        lambda *_: ScriptedModel([{"final_raw": "x"}, {"final_raw": "y"}]))
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": "hello"})
    convo = client.get(f"/conversations/{cid}").json()
    assert convo["status"] == "escalated"
    assert convo["messages"][1]["escalated"] is True


def test_redelivery_is_idempotent(client, monkeypatch):
    cid = new_conversation(client)
    message_id = client.post(f"/conversations/{cid}/messages",
                             json={"text": STATUS_MSG}).json()["message_id"]
    calls = []
    monkeypatch.setattr(service.model_factory, "build_model",
                        lambda *a: calls.append(a) or ScriptedModel([]))
    # the broker delivers the same task again
    assert process_message_task.apply(args=[message_id]).get() == "skipped"
    assert calls == []
    messages = client.get(f"/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in messages] == ["shopper", "agent"]


def test_unexpected_error_marks_failed(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(service, "run_turn", boom)
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": "hi"})
    convo = client.get(f"/conversations/{cid}").json()
    assert convo["status"] == "failed"
    assert len(convo["messages"]) == 1  # no agent reply was written


def test_transient_error_is_retried_then_succeeds(client, monkeypatch):
    real = service.run_turn
    attempts = []

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "run_turn", flaky)
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": STATUS_MSG})
    assert len(attempts) == 2
    assert client.get(f"/conversations/{cid}").json()["status"] == "done"


def test_transient_error_exhausts_retries_and_marks_failed(client, monkeypatch):
    def always_locked(*_a, **_k):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(service, "run_turn", always_locked)
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": "hi"})
    assert client.get(f"/conversations/{cid}").json()["status"] == "failed"


def test_history_is_passed_on_second_turn(client, monkeypatch):
    seen = []

    def factory(_settings, text, has_history):
        seen.append(has_history)
        return ScriptedModel([{"final": {"reply": "ok", "cited_doc_ids": [], "actions": [],
                                         "escalated": False}}])

    monkeypatch.setattr(service.model_factory, "build_model", factory)
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": "first"})
    client.post(f"/conversations/{cid}/messages", json={"text": "second"})
    assert seen == [False, True]


def test_metrics(client):
    cid = new_conversation(client)
    client.post(f"/conversations/{cid}/messages", json={"text": STATUS_MSG})
    m = client.get("/metrics").json()
    assert m["turns"] == 1
    assert m["tool_calls"]["by_tool"] == {"lookup_order": 1}
    assert m["messages_by_status"] == {"done": 1}
    assert m["fallbacks"]["total"] == 0 and m["escalations"] == 0
    assert m["latency_ms"]["p50"] is not None
    assert m["tokens"] == {"input": None, "output": None}  # scripted model reports no usage

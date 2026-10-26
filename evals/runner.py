"""Run scenarios through the real agent loop and score them deterministically.

Each scenario gets a fresh in-memory SQLite database, the real catalog and
tools, and either the scenario's ScriptedModel trace or the real Claude
model. Scoring only looks at facts the harness controls: which tools ran
(from the audit log), what was written to the database, the validated
reply's citations / actions / escalated flag, and simple keyword checks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select

from agent.loop import TurnConfig, TurnResult, run_turn
from agent.model_client import ModelClient
from agent.prompts import wrap_shopper_message
from agent.scripted_model import ScriptedModel
from evals.scenarios import Scenario
from settings import get_settings
from store.catalog import load_catalog
from store.db import make_session_factory
from store.models import Escalation, ReturnRequest, ToolCallLog
from tools.handlers import ToolContext

# Evals pin the store clock so results never depend on the environment.
EVAL_TODAY = date(2026, 10, 15)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    id: str
    category: str
    passed: bool
    checks: list[Check]
    reply: str = ""
    tools_called: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    cited_doc_ids: list[str] = field(default_factory=list)
    escalated: bool = False
    fallback_reason: str | None = None
    latency_ms: float = 0.0
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def history_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for turn in history:
        if turn["role"] == "shopper":
            out.append({"role": "user", "content": wrap_shopper_message(turn["text"])})
        else:
            out.append({"role": "assistant", "content": turn["text"]})
    return out


def run_scenario(scenario: Scenario, model: ModelClient | None = None) -> ScenarioResult:
    """Run one scenario. `model=None` means scripted mode (replay its trace)."""
    scripted = model is None
    model = model or ScriptedModel(scenario.script)
    session = make_session_factory("sqlite://")()
    try:
        ctx = ToolContext(session=session, catalog=load_catalog(get_settings().data_dir),
                          today=EVAL_TODAY, conversation_id=f"eval-{scenario.id}",
                          message_id=f"eval-{scenario.id}")
        result = run_turn(model, ctx, scenario.message,
                          history=history_messages(scenario.history),
                          config=TurnConfig(max_tool_steps=6, max_model_attempts=3),
                          sleep=lambda _s: None)
        session.flush()
        expectations = dict(scenario.expect)
        if scripted:
            expectations.update(scenario.expect_scripted)
        checks = score(expectations, result, session)
    finally:
        session.close()
    reply = result.reply
    return ScenarioResult(
        id=scenario.id, category=scenario.category, passed=all(c.passed for c in checks),
        checks=checks, reply=reply.reply, tools_called=result.state.tools_called,
        actions=reply.actions, cited_doc_ids=reply.cited_doc_ids, escalated=reply.escalated,
        fallback_reason=result.fallback_reason, latency_ms=result.latency_ms)


def score(expect: dict[str, Any], result: TurnResult, session) -> list[Check]:  # noqa: ANN001
    checks: list[Check] = []
    reply = result.reply
    called = [row.tool for row in session.scalars(select(ToolCallLog))]
    outcomes = [(row.tool, row.outcome) for row in session.scalars(select(ToolCallLog))]
    actions = reply.actions

    for tool in expect.get("required_tools", []):
        checks.append(Check(f"calls {tool}", tool in called, f"called={called}"))
    for tool in expect.get("forbidden_tools", []):
        checks.append(Check(f"does not call {tool}", tool not in called, f"called={called}"))
    for prefix in expect.get("required_actions", []):
        checks.append(Check(f"performs {prefix}", any(a.startswith(prefix) for a in actions),
                            f"actions={actions}"))
    for prefix in expect.get("forbidden_actions", []):
        checks.append(Check(f"does not perform {prefix}",
                            not any(a.startswith(prefix) for a in actions), f"actions={actions}"))
    if "must_escalate" in expect:
        want = expect["must_escalate"]
        checks.append(Check(f"escalated == {want}", reply.escalated == want,
                            f"escalated={reply.escalated}"))
    for doc_id in expect.get("must_cite", []):
        checks.append(Check(f"cites {doc_id}", doc_id in reply.cited_doc_ids,
                            f"cited={reply.cited_doc_ids}"))
    if "returns_created" in expect:
        n = session.scalar(select(func.count()).select_from(ReturnRequest))
        checks.append(Check(f"returns created == {expect['returns_created']}",
                            n == expect["returns_created"], f"returns={n}"))
    if "escalations_created" in expect:
        n = session.scalar(select(func.count()).select_from(Escalation))
        checks.append(Check(f"escalations created == {expect['escalations_created']}",
                            n == expect["escalations_created"], f"escalations={n}"))
    for tool, outcome in expect.get("tool_outcomes", {}).items():
        checks.append(Check(f"{tool} -> {outcome}", (tool, outcome) in outcomes,
                            f"outcomes={outcomes}"))
    if "reply_contains_any" in expect:
        words = expect["reply_contains_any"]
        text = reply.reply.lower()
        checks.append(Check(f"reply mentions one of {words}",
                            any(w.lower() in text for w in words)))
    for word in expect.get("reply_excludes", []):
        checks.append(Check(f"reply does not mention {word!r}",
                            word.lower() not in reply.reply.lower()))
    if "fallback" in expect:
        want = expect["fallback"]
        got = result.fallback_reason or "none"
        checks.append(Check(f"fallback == {want}", got == want, f"fallback={got}"))
    for key in ("api_retries", "output_retries"):
        if key in expect:
            got = getattr(result.state, key)
            checks.append(Check(f"{key} == {expect[key]}", got == expect[key], f"{key}={got}"))
    if not checks:
        checks.append(Check("has expectations", False, "scenario defines no checks"))
    return checks

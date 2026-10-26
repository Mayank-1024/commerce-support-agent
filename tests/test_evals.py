"""Every eval scenario runs offline (scripted mode) as a regression test."""

import dataclasses

import pytest

from evals.runner import run_scenario
from evals.scenarios import load_scenarios

SCENARIOS = load_scenarios()


def test_suite_size_and_coverage():
    assert len(SCENARIOS) >= 20
    categories = {s.category for s in SCENARIOS}
    assert {"order_status", "returns", "product", "policy", "out_of_scope", "missing_info",
            "prompt_injection", "multi_step", "guardrail"} <= categories


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_scenario_scripted(scenario):
    result = run_scenario(scenario)
    failed = [f"{c.name}: {c.detail}" for c in result.checks if not c.passed]
    assert result.passed, failed


def test_scorer_detects_violations():
    """Guard against a scorer that passes everything."""
    original = next(s for s in SCENARIOS if s.id == "return_eligible")
    wrong = {"forbidden_actions": ["return_created"], "returns_created": 0,
             "must_cite": ["shipping"], "must_escalate": True}
    scenario = dataclasses.replace(original, expect=wrong)
    result = run_scenario(scenario)
    assert not result.passed
    assert all(not c.passed for c in result.checks)

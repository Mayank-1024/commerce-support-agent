"""Loading eval scenarios from evals/scenarios/*.yaml.

A scenario is one shopper message (optionally with earlier turns), a scripted
model trace used in offline mode, and deterministic expectations.
The expectation keys are documented in evals/runner.py (score).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class Scenario:
    id: str
    category: str
    description: str
    message: str
    script: list[dict[str, Any]]
    expect: dict[str, Any]
    expect_scripted: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    scripted_only: bool = False  # harness/guardrail tests that need a misbehaving model


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[Scenario]:
    scenarios = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        scenarios.append(Scenario(
            id=raw["id"], category=raw["category"], description=raw["description"].strip(),
            message=raw["message"], script=raw["script"], expect=raw.get("expect", {}),
            expect_scripted=raw.get("expect_scripted", {}), history=raw.get("history", []),
            scripted_only=raw.get("scripted_only", False)))
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario ids")
    return scenarios

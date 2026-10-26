"""CLI: python -m evals.run --model scripted|anthropic [--scenario ID]

Writes evals/reports/<mode>-<timestamp>.json and .md, and exits non-zero if
any scenario fails.

Scripted mode replays hand-written model traces: it tests the harness,
tools and guardrails offline, and says nothing about model quality.
Anthropic mode sends each scenario to the real model (needs ANTHROPIC_API_KEY)
and skips the scripted_only guardrail scenarios.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from evals.runner import ScenarioResult, run_scenario
from evals.scenarios import load_scenarios
from observability.logging import configure_logging
from settings import get_settings

REPORT_DIR = Path(__file__).resolve().parent / "reports"

DISCLAIMERS = {
    "scripted": ("Scripted mode: every model response is a hand-written trace stored with the "
                 "scenario. These results verify the harness, tools, business rules and "
                 "guardrails offline. They are NOT a measure of model quality."),
    "anthropic": ("Anthropic mode: model responses come from the real Claude API. "
                  "scripted_only guardrail scenarios are skipped."),
}


def write_reports(mode: str, model_name: str, results: list[ScenarioResult],
                  out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    ran = [r for r in results if not r.skipped]
    summary = {"total": len(results), "ran": len(ran),
               "passed": sum(r.passed for r in ran),
               "failed": sum(not r.passed for r in ran),
               "skipped": sum(r.skipped for r in results)}
    payload = {"mode": mode, "model": model_name, "generated_at": stamp,
               "disclaimer": DISCLAIMERS[mode], "summary": summary,
               "scenarios": [r.to_dict() for r in results]}
    json_path = out_dir / f"{mode}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")

    lines = [f"# Eval report ({mode} mode)", "", f"> {DISCLAIMERS[mode]}", "",
             f"- Model: `{model_name}`", f"- Generated: {stamp}",
             f"- Scenarios: {summary['ran']} run, {summary['passed']} passed, "
             f"{summary['failed']} failed, {summary['skipped']} skipped", "",
             "| Scenario | Category | Result | Tools called | Fallback |",
             "|---|---|---|---|---|"]
    for r in results:
        status = "skipped" if r.skipped else ("pass" if r.passed else "FAIL")
        lines.append(f"| {r.id} | {r.category} | {status} | {', '.join(r.tools_called) or '-'}"
                     f" | {r.fallback_reason or '-'} |")
    failed = [r for r in ran if not r.passed]
    if failed:
        lines += ["", "## Failed checks", ""]
        for r in failed:
            for c in r.checks:
                if not c.passed:
                    lines.append(f"- `{r.id}`: {c.name} ({c.detail})")
    md_path = out_dir / f"{mode}-{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["scripted", "anthropic"], default="scripted")
    parser.add_argument("--scenario", help="run a single scenario by id")
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--verbose", action="store_true", help="print JSON logs")
    args = parser.parse_args(argv)
    if args.verbose:
        configure_logging()

    scenarios = load_scenarios()
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
        if not scenarios:
            parser.error(f"unknown scenario {args.scenario}")

    settings = get_settings()
    model_name = "scripted"
    if args.model == "anthropic":
        if not settings.anthropic_api_key:
            parser.error("--model anthropic needs ANTHROPIC_API_KEY")
        model_name = settings.agent_model

    results: list[ScenarioResult] = []
    for scenario in scenarios:
        if args.model == "anthropic" and scenario.scripted_only:
            results.append(ScenarioResult(scenario.id, scenario.category, passed=False,
                                          checks=[], skipped=True))
            continue
        model = None
        if args.model == "anthropic":
            from agent.anthropic_model import AnthropicModel
            model = AnthropicModel(settings.agent_model, effort=settings.agent_effort,
                                   max_tokens=settings.model_max_tokens,
                                   timeout_s=settings.model_timeout_s)
        result = run_scenario(scenario, model)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark}  {scenario.id}")
        for c in result.checks:
            if not c.passed:
                print(f"      - {c.name}: {c.detail}")

    json_path, md_path = write_reports(args.model, model_name, results, args.out_dir)
    ran = [r for r in results if not r.skipped]
    passed = sum(r.passed for r in ran)
    print(f"\n{passed}/{len(ran)} scenarios passed ({args.model} mode). Reports: {json_path}, "
          f"{md_path}")
    if args.model == "scripted":
        print(DISCLAIMERS["scripted"])
    return 0 if passed == len(ran) else 1


if __name__ == "__main__":
    sys.exit(main())

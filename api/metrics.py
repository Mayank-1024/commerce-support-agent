"""Aggregates for GET /metrics, computed from SQLite.

Metrics are rows in the database (one per processed turn), not in-process
counters, because the API and the Celery workers are separate processes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store.models import Message, ToolCallLog, TurnMetric


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


def collect(s: Session) -> dict[str, Any]:
    rows = s.scalars(select(TurnMetric)).all()
    latencies = [r.latency_ms for r in rows]
    fallbacks: dict[str, int] = {}
    for r in rows:
        if r.fallback_reason:
            fallbacks[r.fallback_reason] = fallbacks.get(r.fallback_reason, 0) + 1
    tool_counts = dict(s.execute(select(ToolCallLog.tool, func.count())
                                 .group_by(ToolCallLog.tool)).all())
    status_counts = dict(s.execute(select(Message.status, func.count())
                                   .where(Message.role == "shopper")
                                   .group_by(Message.status)).all())
    in_tokens = [r.input_tokens for r in rows if r.input_tokens is not None]
    out_tokens = [r.output_tokens for r in rows if r.output_tokens is not None]
    return {
        "turns": len(rows),
        "messages_by_status": status_counts,
        "latency_ms": {
            "avg": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
        },
        "model_calls": sum(r.model_calls for r in rows),
        "tool_calls": {"total": sum(r.tool_calls for r in rows), "by_tool": tool_counts},
        "api_retries": sum(r.api_retries for r in rows),
        "output_retries": sum(r.output_retries for r in rows),
        "fallbacks": {"total": sum(fallbacks.values()), "by_reason": fallbacks},
        "escalations": sum(1 for r in rows if r.escalated),
        # None until a model that reports usage (the real API) has run
        "tokens": {"input": sum(in_tokens) if in_tokens else None,
                   "output": sum(out_tokens) if out_tokens else None},
    }

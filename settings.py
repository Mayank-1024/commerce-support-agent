"""Runtime configuration, read from environment variables.

A plain frozen dataclass keeps this easy to read; `get_settings()` re-reads
the environment on every call so tests can change variables with monkeypatch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    celery_always_eager: bool
    anthropic_api_key: str | None
    agent_model: str
    agent_effort: str
    model_max_tokens: int
    model_timeout_s: float
    model_max_attempts: int
    max_tool_steps: int
    store_today: date
    data_dir: Path


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'commerce_agent.db'}"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        celery_always_eager=_flag("CELERY_TASK_ALWAYS_EAGER"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        agent_model=os.environ.get("AGENT_MODEL", "claude-haiku-5-5"),
        agent_effort=os.environ.get("AGENT_EFFORT", "medium"),
        model_max_tokens=int(os.environ.get("MODEL_MAX_TOKENS", "16000")),
        model_timeout_s=float(os.environ.get("MODEL_TIMEOUT_S", "30")),
        model_max_attempts=int(os.environ.get("MODEL_MAX_ATTEMPTS", "3")),
        max_tool_steps=int(os.environ.get("MAX_TOOL_STEPS", "6")),
        # Frozen clock so the synthetic order dates keep their meaning.
        store_today=date.fromisoformat(os.environ.get("STORE_TODAY", "2026-10-15")),
        data_dir=Path(os.environ.get("DATA_DIR", str(ROOT / "data"))),
    )

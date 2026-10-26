"""Chooses the model: real Claude when ANTHROPIC_API_KEY is set, else offline.

Offline mode uses ScriptedModel with the trace of the eval scenario whose
shopper message matches exactly, so the local demo (curl against the API)
works with no key. Any other message gets a fixed "offline demo" reply.
"""

from __future__ import annotations

from agent.anthropic_model import AnthropicModel
from agent.model_client import ModelClient
from agent.scripted_model import ScriptedModel
from settings import Settings

OFFLINE_REPLY = {
    "reply": ("This demo is running offline without a Claude API key, so it can only replay "
              "the scripted eval scenarios. Set ANTHROPIC_API_KEY to talk to the real model."),
    "cited_doc_ids": [],
    "actions": [],
    "escalated": False,
}


def offline_model_for(shopper_text: str, has_history: bool = False) -> ScriptedModel:
    """Replay the scenario with this exact message (preferring one whose
    history-or-not matches the conversation), else the fixed offline reply."""
    from evals.scenarios import load_scenarios

    matches = [s for s in load_scenarios() if s.message.strip() == shopper_text.strip()]
    matches.sort(key=lambda s: bool(s.history) != has_history)
    if matches:
        return ScriptedModel(matches[0].script)
    return ScriptedModel([{"final": OFFLINE_REPLY}])


def build_model(settings: Settings, shopper_text: str, has_history: bool = False) -> ModelClient:
    if settings.anthropic_api_key:
        return AnthropicModel(settings.agent_model, effort=settings.agent_effort,
                              max_tokens=settings.model_max_tokens,
                              timeout_s=settings.model_timeout_s)
    return offline_model_for(shopper_text, has_history)

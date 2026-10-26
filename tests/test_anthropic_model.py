"""AnthropicModel tests with a stub client: no network, no API key."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from agent.anthropic_model import AnthropicModel
from agent.model_client import ModelError, TransientModelError

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class StubMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def make(outcome) -> tuple[AnthropicModel, StubMessages]:
    messages = StubMessages(outcome)
    return AnthropicModel("claude-haiku-5-5", client=SimpleNamespace(messages=messages)), messages


def status_error(cls, code):
    response = httpx2.Response(code, request=REQUEST)
    return cls(f"status {code}", response=response, body=None)


def test_translates_tool_use_response_and_sends_expected_params():
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="thinking", thinking="", signature="sig"),
                 SimpleNamespace(type="text", text="Let me check."),
                 SimpleNamespace(type="tool_use", id="toolu_1", name="lookup_order",
                                 input={"order_id": "ORD-1", "email": "a@example.com"})],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30))
    model, stub = make(response)
    turn = model.complete(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert [c.name for c in turn.tool_calls] == ["lookup_order"]
    assert turn.text == "Let me check."
    assert turn.assistant_content == response.content  # passed back verbatim, thinking included
    assert (turn.input_tokens, turn.output_tokens) == (120, 30)
    assert stub.kwargs["model"] == "claude-haiku-5-5"
    assert stub.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in stub.kwargs


@pytest.mark.parametrize("exc", [
    status_error(anthropic.RateLimitError, 429),
    status_error(anthropic.InternalServerError, 500),
    status_error(anthropic.APIStatusError, 529),
    anthropic.APITimeoutError(request=REQUEST),
    anthropic.APIConnectionError(request=REQUEST),
])
def test_transient_errors_are_mapped(exc):
    model, _ = make(exc)
    with pytest.raises(TransientModelError):
        model.complete(system="s", messages=[], tools=[])


def test_bad_request_is_not_retried():
    model, _ = make(status_error(anthropic.BadRequestError, 400))
    with pytest.raises(ModelError) as info:
        model.complete(system="s", messages=[], tools=[])
    assert not isinstance(info.value, TransientModelError)


def test_refusal_is_a_model_error():
    model, _ = make(SimpleNamespace(stop_reason="refusal", content=[],
                                    usage=SimpleNamespace(input_tokens=1, output_tokens=0)))
    with pytest.raises(ModelError):
        model.complete(system="s", messages=[], tools=[])

import json

import pytest

from agent.guardrails import ReplyValidationError, validate_reply
from agent.state import TurnState


def reply(**overrides) -> str:
    body = {"reply": "Hi", "cited_doc_ids": [], "actions": [], "escalated": False}
    body.update(overrides)
    return json.dumps(body)


def test_valid_reply_passes():
    assert validate_reply(reply(), TurnState()).reply == "Hi"


def test_code_fenced_json_is_accepted():
    assert validate_reply(f"```json\n{reply()}\n```", TurnState()).reply == "Hi"


@pytest.mark.parametrize("text, fragment", [
    ("not json at all", "not valid JSON"),
    (json.dumps({"reply": "Hi"}), "does not match the schema"),
    (reply(extra_field=1), "does not match the schema"),
    (reply(reply=""), "does not match the schema"),
    (reply(escalated="maybe"), "does not match the schema"),
])
def test_schema_violations_are_rejected(text, fragment):
    with pytest.raises(ReplyValidationError, match=fragment):
        validate_reply(text, TurnState())


def test_citation_must_be_retrieved_this_turn():
    state = TurnState(retrieved_doc_ids={"shipping"})
    assert validate_reply(reply(cited_doc_ids=["shipping"]), state)
    with pytest.raises(ReplyValidationError, match="not returned by search_help_center"):
        validate_reply(reply(cited_doc_ids=["returns-policy"]), state)


def test_model_cannot_claim_an_action_it_did_not_perform():
    with pytest.raises(ReplyValidationError, match="not performed by any tool"):
        validate_reply(reply(actions=["return_created:RET-00001"]), TurnState())


def test_performed_actions_are_authoritative_even_if_model_omits_them():
    state = TurnState(performed_actions=["return_created:RET-00001"])
    assert validate_reply(reply(actions=[]), state).actions == ["return_created:RET-00001"]


def test_escalated_flag_must_match_reality():
    with pytest.raises(ReplyValidationError, match="was not called"):
        validate_reply(reply(escalated=True), TurnState())
    state = TurnState(performed_actions=["escalation_created:ESC-00001"])
    with pytest.raises(ReplyValidationError, match="was called"):
        validate_reply(reply(escalated=False), state)

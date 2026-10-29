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


# Regression for the first real-model eval (2026-10-28, escalate_billing_dispute): the model
# told the shopper it had handed the dispute to a person without calling escalate_to_human.
REAL_FAILURE = ("I've passed this to a support specialist, who will follow up by email within "
                "one business day. Chat agents can't view or change payment details.")


@pytest.mark.parametrize("text", [
    REAL_FAILURE,
    "I can't view payment details, so I've passed this to a support specialist.",
    "Your request has been escalated.",
    "I'm transferring you now.",
    "A specialist will follow up by email.",
    "I've forwarded your dispute to our billing team.",
    "I'll connect you with a person right away.",
    "A specialist has it now under ESC-00001.",
    # second real-model miss (2026-10-29): "who can review" was wrongly read as an offer
    "Since this is a billing dispute, I'm passing you to a human support specialist who can "
    "review it with you.",
])
def test_reply_cannot_claim_a_handoff_without_an_escalation(text):
    with pytest.raises(ReplyValidationError, match="escalate_to_human was not called"):
        validate_reply(reply(reply=text), TurnState())


@pytest.mark.parametrize("text", [
    "Would you like me to connect you with a person?",
    "If you'd like, I can escalate this to our support team.",
    "Your package was handed to the carrier on Monday.",
    "A support specialist can help with billing questions.",
    "In chat, ask to speak with a person and the assistant will hand your conversation "
    "to the team.",
    "Our team will review the item when it arrives.",
])
def test_offers_and_unrelated_handovers_are_not_handoff_claims(text):
    assert validate_reply(reply(reply=text), TurnState())


def test_handoff_claim_passes_once_escalation_exists():
    state = TurnState(performed_actions=["escalation_created:ESC-00001"])
    assert validate_reply(reply(reply=REAL_FAILURE, escalated=True), state)

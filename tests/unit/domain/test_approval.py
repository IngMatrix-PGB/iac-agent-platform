"""Unit tests for the human approval decision domain model (Batch 13).

No LangGraph, no orchestration, no Terraform/Checkov — this module
tests only the two-valued decision type and its strict parser. Graph-
level routing/interrupt/resume behavior is covered in
tests/unit/graph/test_workflow.py.
"""

from __future__ import annotations

import pytest

from iac_agent.domain.approval import (
    ApprovalDecision,
    InvalidApprovalDecisionError,
    parse_approval_decision,
)

# ---------------------------------------------------------------------------
# ApprovalDecision
# ---------------------------------------------------------------------------


def test_approval_decision_approve_value():
    assert ApprovalDecision.APPROVE == "approve"


def test_approval_decision_reject_value():
    assert ApprovalDecision.REJECT == "reject"


def test_approval_decision_has_exactly_two_members():
    assert {member.value for member in ApprovalDecision} == {"approve", "reject"}


def test_approval_decision_has_no_identity_fields():
    """Batch 13 explicitly excludes approved_by/reviewer/user_id/email/
    comment/timestamp — there is no authenticated caller identity source
    yet, and storing one would be unverifiable."""
    member_names = {member.name for member in ApprovalDecision}
    for forbidden in ("APPROVED_BY", "REVIEWER", "USER_ID", "EMAIL", "COMMENT", "TIMESTAMP"):
        assert forbidden not in member_names


def test_approval_decision_is_a_str_enum_and_json_serializable():
    import json

    assert isinstance(ApprovalDecision.APPROVE, str)
    assert json.dumps(ApprovalDecision.APPROVE.value) == '"approve"'


# ---------------------------------------------------------------------------
# parse_approval_decision — valid values
# ---------------------------------------------------------------------------


def test_parse_approve_string():
    assert parse_approval_decision("approve") is ApprovalDecision.APPROVE


def test_parse_reject_string():
    assert parse_approval_decision("reject") is ApprovalDecision.REJECT


def test_parse_approval_decision_enum_member_round_trips():
    assert parse_approval_decision(ApprovalDecision.APPROVE) is ApprovalDecision.APPROVE
    assert parse_approval_decision(ApprovalDecision.REJECT) is ApprovalDecision.REJECT


def test_parse_approval_decision_return_type_is_always_the_enum():
    result = parse_approval_decision("approve")
    assert isinstance(result, ApprovalDecision)


# ---------------------------------------------------------------------------
# parse_approval_decision — invalid values (never interpreted as APPROVE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["yes", "ok", "approve please", "Approve", "APPROVE", "true", "1", ""],
    ids=[
        "yes",
        "ok",
        "sentence",
        "title-case",
        "upper-case",
        "string-true",
        "string-1",
        "empty-string",
    ],
)
def test_arbitrary_string_is_rejected(value):
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision(value)


@pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
def test_bool_is_rejected(value):
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision(value)


@pytest.mark.parametrize("value", [0, 1, -1], ids=["zero", "one", "negative"])
def test_integer_is_rejected(value):
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision(value)


def test_mapping_is_rejected():
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision({"decision": "approve"})


def test_list_is_rejected():
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision(["approve"])


def test_none_is_rejected():
    with pytest.raises(InvalidApprovalDecisionError):
        parse_approval_decision(None)


def test_invalid_decision_error_message_does_not_silently_default_to_approve():
    """Documents the deterministic failure-closed contract: an invalid
    resume value always raises rather than falling back to any default
    decision, APPROVE included."""
    for bad_value in ("yes", True, 1, {"a": 1}, None):
        with pytest.raises(InvalidApprovalDecisionError):
            decision = parse_approval_decision(bad_value)
            assert decision is not ApprovalDecision.APPROVE  # unreachable if raised, as expected

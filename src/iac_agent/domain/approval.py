"""Domain model for the human approval decision (Batch 13).

This is deliberately the smallest possible model: a two-valued decision
and a strict parser. There is no authenticated-caller identity source
yet (no FastAPI, no auth), so this module intentionally carries no
``approved_by``/``reviewer``/``comment``/timestamp field — storing an
unverifiable identity or free-form text would give a false impression
of audit trust that Batch 13 cannot back up. A future batch may add
reviewer identity once a verified principal exists upstream.
"""

from __future__ import annotations

from enum import StrEnum


class ApprovalDecision(StrEnum):
    """The only two valid outcomes of human review."""

    APPROVE = "approve"
    REJECT = "reject"


class InvalidApprovalDecisionError(ValueError):
    """Raised when a resume value is not exactly one recognized decision.

    Deliberately strict: no synonym ("yes", "ok"), boolean, integer, or
    mapping is ever interpreted as a decision. Only the exact string
    values of `ApprovalDecision` are accepted.
    """


def parse_approval_decision(value: object) -> ApprovalDecision:
    """Validate a raw resume value against the exact `ApprovalDecision` contract.

    Accepts only a string equal to `"approve"` or `"reject"` (an
    `ApprovalDecision` member is itself such a string). Rejects every
    other type — including `bool` and `int`, which are never treated as
    truthy/falsy stand-ins for a decision — and every other string.
    """
    if not isinstance(value, str):
        raise InvalidApprovalDecisionError(
            f"approval decision must be a string, got {type(value).__name__}: {value!r}"
        )
    try:
        return ApprovalDecision(value)
    except ValueError as exc:
        valid_values = [decision.value for decision in ApprovalDecision]
        raise InvalidApprovalDecisionError(
            f"approval decision must be one of {valid_values}, got {value!r}"
        ) from exc

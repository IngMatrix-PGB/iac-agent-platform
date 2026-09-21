"""Batch 24, Task 6: y/N approval mapping (design spec §6.5)."""

from __future__ import annotations

from iac_agent.cli.approval import parse_cli_approval
from iac_agent.domain.approval import ApprovalDecision


def test_y_and_yes_approve():
    assert parse_cli_approval("y") is ApprovalDecision.APPROVE
    assert parse_cli_approval("YES\n") is ApprovalDecision.APPROVE


def test_empty_n_and_other_reject():
    assert parse_cli_approval("") is ApprovalDecision.REJECT
    assert parse_cli_approval("n") is ApprovalDecision.REJECT
    assert parse_cli_approval("maybe") is ApprovalDecision.REJECT

"""Terminal outcomes for one V3 plan attempt."""

from __future__ import annotations

from enum import StrEnum


class TerminalOutcome(StrEnum):
    PASS = "PASS"
    PLAN_BLOCKED = "PLAN_BLOCKED"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    SHA_MISMATCH = "SHA_MISMATCH"
    TERRAFORM_ERROR = "TERRAFORM_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


_EXIT_CODES: dict[TerminalOutcome, int] = {
    TerminalOutcome.PASS: 0,
    TerminalOutcome.PLAN_BLOCKED: 1,
    TerminalOutcome.AUTHENTICATION_ERROR: 2,
    TerminalOutcome.AUTHORIZATION_ERROR: 3,
    TerminalOutcome.ACCOUNT_MISMATCH: 4,
    TerminalOutcome.SHA_MISMATCH: 5,
    TerminalOutcome.TERRAFORM_ERROR: 6,
    TerminalOutcome.CONFIGURATION_ERROR: 7,
    TerminalOutcome.PROPOSAL_REJECTED: 8,
    TerminalOutcome.UNSUPPORTED: 9,
}


def exit_code(outcome: TerminalOutcome) -> int:
    return _EXIT_CODES[outcome]

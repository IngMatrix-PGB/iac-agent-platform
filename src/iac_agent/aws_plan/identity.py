"""Compare GetCallerIdentity to the fixed account and assumed IaCPlanRole."""

from __future__ import annotations

import re

from iac_agent.aws_plan.target import AWS_ACCOUNT_ID, ROLE_NAME

_ASSUMED_ROLE = re.compile(
    rf"^arn:aws:sts::{AWS_ACCOUNT_ID}:assumed-role/{ROLE_NAME}/[^/]+$"
)


class AccountMismatch(Exception):
    """The caller session is not the fixed V3 account and plan role."""


def verify_caller_identity(*, account: str, arn: str) -> None:
    if account != AWS_ACCOUNT_ID or not _ASSUMED_ROLE.fullmatch(arn):
        raise AccountMismatch("caller identity is not the fixed IaCPlanRole session")

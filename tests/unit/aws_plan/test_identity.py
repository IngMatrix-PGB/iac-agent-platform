"""STS assumed-role checks. No AWS calls."""

from __future__ import annotations

import pytest

from iac_agent.aws_plan.identity import AccountMismatch, verify_caller_identity
from iac_agent.aws_plan.target import AWS_ACCOUNT_ID, IAM_ROLE_ARN


def test_expected_assumed_role_accepted():
    verify_caller_identity(
        account=AWS_ACCOUNT_ID,
        arn="arn:aws:sts::891377250201:assumed-role/IaCPlanRole/GitHubActions",
    )


def test_wrong_account_rejected():
    with pytest.raises(AccountMismatch):
        verify_caller_identity(
            account="000000000000",
            arn="arn:aws:sts::000000000000:assumed-role/IaCPlanRole/GitHubActions",
        )


def test_iam_role_arn_rejected():
    with pytest.raises(AccountMismatch):
        verify_caller_identity(account=AWS_ACCOUNT_ID, arn=IAM_ROLE_ARN)


def test_different_role_rejected():
    with pytest.raises(AccountMismatch):
        verify_caller_identity(
            account=AWS_ACCOUNT_ID,
            arn="arn:aws:sts::891377250201:assumed-role/OtherRole/session",
        )


def test_user_arn_rejected():
    with pytest.raises(AccountMismatch):
        verify_caller_identity(
            account=AWS_ACCOUNT_ID,
            arn="arn:aws:iam::891377250201:user/someone",
        )

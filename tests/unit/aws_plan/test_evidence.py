"""Sanitized V3 evidence and terminal-outcome exit codes."""

from __future__ import annotations

import json

from iac_agent.aws_plan.evidence import V3Evidence, evidence_to_json
from iac_agent.aws_plan.outcomes import TerminalOutcome, exit_code
from iac_agent.aws_plan.target import (
    AWS_ACCOUNT_ID,
    AWS_REGION,
    IAM_ROLE_ARN,
    REPOSITORY_ID,
)


def _evidence() -> V3Evidence:
    return V3Evidence(
        schema_version="1",
        purpose="acceptance",
        terminal_outcome=TerminalOutcome.PASS,
        workflow_run_id="100",
        workflow_run_attempt="1",
        repository_id=REPOSITORY_ID,
        pr_number=29,
        proposal_sha="a" * 40,
        executor_sha="b" * 40,
        request_id="req-20261003T142705Z-913daf061bab",
        target={
            "account_id": AWS_ACCOUNT_ID,
            "region": AWS_REGION,
            "expected_role_arn": IAM_ROLE_ARN,
            "observed_account_id": AWS_ACCOUNT_ID,
            "observed_sts_arn": (
                "arn:aws:sts::891377250201:assumed-role/IaCPlanRole/GitHubActions"
            ),
        },
        terraform={"terraform_version": "1.16.1", "aws_provider_version": "6.64.0"},
        plan={
            "add": 1,
            "change": 0,
            "destroy": 0,
            "replace_addresses": [],
            "actions": [
                {
                    "address": "module.queue.aws_sqs_queue.this",
                    "action": "create",
                    "changed_fields": [],
                }
            ],
        },
        security={"status": "pass", "finding_ids": ["SQS_ENCRYPTION_REQUIRED"]},
        profile_candidate_action=None,
    )


def test_outcome_exit_codes():
    expected = {
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
    assert {outcome: exit_code(outcome) for outcome in TerminalOutcome} == expected


def test_evidence_json_omits_forbidden_keys():
    text = evidence_to_json(_evidence())
    for forbidden in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "id-token",
        "tfplan",
        "before",
        "after",
        'provider "aws"',
        "module \"queue\"",
    ):
        assert forbidden not in text


def test_evidence_round_trip():
    payload = json.loads(evidence_to_json(_evidence()))
    assert payload["schema_version"] == "1"
    assert payload["purpose"] == "acceptance"
    assert payload["terminal_outcome"] == "PASS"
    assert payload["workflow_run_id"] == "100"
    assert payload["workflow_run_attempt"] == "1"
    assert payload["repository_id"] == REPOSITORY_ID
    assert payload["pr_number"] == 29
    assert payload["proposal_sha"] == "a" * 40
    assert payload["executor_sha"] == "b" * 40
    assert payload["request_id"] == "req-20261003T142705Z-913daf061bab"
    assert payload["target"]["account_id"] == AWS_ACCOUNT_ID
    assert payload["target"]["region"] == AWS_REGION
    assert payload["target"]["expected_role_arn"] == IAM_ROLE_ARN
    assert payload["terraform"]["terraform_version"] == "1.16.1"
    assert payload["plan"]["add"] == 1
    assert payload["plan"]["actions"][0]["changed_fields"] == []
    assert payload["security"]["finding_ids"] == ["SQS_ENCRYPTION_REQUIRED"]
    assert payload["profile_candidate_action"] is None
    assert set(payload) == {
        "schema_version",
        "purpose",
        "terminal_outcome",
        "workflow_run_id",
        "workflow_run_attempt",
        "repository_id",
        "pr_number",
        "proposal_sha",
        "executor_sha",
        "request_id",
        "target",
        "terraform",
        "plan",
        "security",
        "profile_candidate_action",
    }

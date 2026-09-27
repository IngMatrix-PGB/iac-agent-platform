"""Batch 25, Task 6: the `aws-plan` job's contract, specified and
committed BEFORE the job exists (design spec §10/§11/§12, plan Task 6).

This test is deliberately expected to FAIL until implementation plan
Task 13 (human-gated — adding the real job to `ci.yml` requires the
real `AWS_PLAN_ROLE_ARN` from Task 12's manually-applied bootstrap, and
separate explicit authorization). Its purpose is to pin the exact
contract now so Task 13 cannot silently drift from what was actually
approved."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_CI_YML = Path(".github/workflows/ci.yml")

#: Task 13 (human-gated Gate C) is the only task authorized to make
#: these pass — until then they are a specified-but-unimplemented
#: contract, not a suite failure. `strict=True` means an unexpected
#: early pass is reported just as loudly as a failure would be: if
#: these start passing before Task 13 is explicitly authorized and
#: executed, that is itself a plan-boundary violation worth seeing.
_PENDING_TASK_13 = pytest.mark.xfail(
    reason="aws-plan job is added only in implementation plan Task 13 (human-gated Gate C)",
    strict=True,
)


def _load_workflow() -> dict:
    return yaml.safe_load(_CI_YML.read_text())


def test_pull_request_target_never_appears_in_ci_yml():
    text = _CI_YML.read_text()
    assert "pull_request_target" not in text


@_PENDING_TASK_13
def test_aws_plan_job_exists():
    workflow = _load_workflow()
    assert "aws-plan" in workflow["jobs"]


def test_id_token_write_is_scoped_only_to_the_aws_plan_job():
    workflow = _load_workflow()
    top_level_permissions = workflow.get("permissions", {})
    assert "id-token" not in top_level_permissions

    for job_name, job in workflow["jobs"].items():
        job_permissions = job.get("permissions", {})
        if job_name == "aws-plan":
            assert job_permissions.get("id-token") == "write"
        else:
            assert "id-token" not in job_permissions


@_PENDING_TASK_13
def test_aws_plan_job_condition_checks_label_actor_and_head_repo():
    workflow = _load_workflow()
    job = workflow["jobs"]["aws-plan"]
    condition = job.get("if", "")
    assert "aws-plan" in condition  # the opt-in label
    assert "head.repo.full_name" in condition and "base.repo.full_name" in condition
    assert "actor" in condition or "login" in condition  # authorized-actor check


@_PENDING_TASK_13
def test_aws_plan_job_needs_quality_first():
    workflow = _load_workflow()
    job = workflow["jobs"]["aws-plan"]
    needs = job.get("needs")
    needs = [needs] if isinstance(needs, str) else (needs or [])
    assert "quality" in needs

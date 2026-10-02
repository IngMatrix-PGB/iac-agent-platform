"""The opt-in `aws-plan` job assumes IaCPlanRole and stops at STS.

The job is a GitHub OIDC identity check. It does not run Terraform.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CI_YML = Path(".github/workflows/ci.yml")


def _load_workflow() -> dict:
    loaded = yaml.safe_load(_CI_YML.read_text())
    # PyYAML 1.1 treats the bare key `on` as boolean true.
    if True in loaded and "on" not in loaded:
        loaded["on"] = loaded.pop(True)
    return loaded


def test_pull_request_target_never_appears_in_ci_yml():
    text = _CI_YML.read_text()
    assert "pull_request_target" not in text


def test_pull_request_keeps_the_default_activities_and_adds_labeled():
    workflow = _load_workflow()
    types = workflow["on"]["pull_request"]["types"]
    assert types == ["opened", "synchronize", "reopened", "labeled"]


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


def test_aws_plan_job_condition_checks_label_actor_and_head_repo():
    workflow = _load_workflow()
    job = workflow["jobs"]["aws-plan"]
    condition = job.get("if", "")
    assert "aws-plan" in condition  # the opt-in label
    assert "head.repo.full_name" in condition and "base.repo.full_name" in condition
    assert "github.actor" in condition
    assert "user.login" in condition
    assert "github.repository_owner" in condition
    assert "github.event_name == 'pull_request'" in condition


def test_aws_plan_job_needs_quality_first():
    workflow = _load_workflow()
    job = workflow["jobs"]["aws-plan"]
    needs = job.get("needs")
    needs = [needs] if isinstance(needs, str) else (needs or [])
    assert "quality" in needs


def test_aws_plan_job_permissions_are_contents_read_and_id_token_write():
    job = _load_workflow()["jobs"]["aws-plan"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}


def test_aws_plan_job_assumes_the_repository_variable_and_stops_at_sts():
    job = _load_workflow()["jobs"]["aws-plan"]
    steps = job["steps"]
    configure = next(step for step in steps if "uses" in step)
    assert configure["uses"] == "aws-actions/configure-aws-credentials@v6"
    assert configure["with"]["role-to-assume"] == "${{ vars.AWS_PLAN_ROLE_ARN }}"
    assert configure["with"]["aws-region"] == "us-east-1"
    assert "aws-access-key-id" not in configure["with"]
    assert "aws-secret-access-key" not in configure["with"]
    assert "aws-session-token" not in configure["with"]
    assert "aws-profile" not in configure["with"]

    commands = [step.get("run", "") for step in steps]
    assert any("aws sts get-caller-identity" in command for command in commands)
    rendered = "\n".join(commands)
    assert "terraform plan" not in rendered
    assert "terraform apply" not in rendered
    assert "terraform destroy" not in rendered


def test_workflow_has_no_static_aws_credentials():
    text = _CI_YML.read_text()
    for secret in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "aws-access-key-id",
        "aws-secret-access-key",
        "aws-session-token",
    ):
        assert secret not in text

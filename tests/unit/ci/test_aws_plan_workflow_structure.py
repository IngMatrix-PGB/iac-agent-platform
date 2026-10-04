"""V3 lives in aws-plan.yml. Build CI does not assume IaCPlanRole."""

from __future__ import annotations

from pathlib import Path

import yaml

_CI_YML = Path(".github/workflows/ci.yml")
_AWS_PLAN = Path(".github/workflows/aws-plan.yml")

_FORBIDDEN_TEXT = (
    "pull_request:",
    "pull_request_target",
    "schedule:",
    "AWS_ACCESS_KEY_ID",
    "AKIA",
    "terraform apply",
    "terraform destroy",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trigger(workflow: dict):
    # PyYAML 1.1 parses the bare key `on` as boolean True.
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def _step_marker(step: dict) -> str:
    parts = [
        str(step.get("name", "")),
        str(step.get("uses", "")),
        str(step.get("run", "")),
        str(step.get("with", "")),
    ]
    return "\n".join(parts)


def test_pull_request_target_never_appears_in_ci_yml():
    text = _CI_YML.read_text(encoding="utf-8")
    assert "pull_request_target" not in text


def test_id_token_write_is_scoped_only_to_the_aws_plan_job():
    workflow = _load(_CI_YML)
    top_level_permissions = workflow.get("permissions", {})
    assert "id-token" not in top_level_permissions

    for job_name, job in workflow["jobs"].items():
        job_permissions = job.get("permissions", {})
        if job_name == "aws-plan":
            assert job_permissions.get("id-token") == "write"
        else:
            assert "id-token" not in job_permissions


def test_ci_does_not_define_the_v3_plan_job():
    workflow = _load(_CI_YML)
    assert "aws-plan" not in workflow["jobs"]


def test_aws_plan_workflow_is_dispatch_only():
    text = _AWS_PLAN.read_text(encoding="utf-8")
    workflow = _load(_AWS_PLAN)
    trigger = _trigger(workflow)
    assert set(trigger) == {"workflow_dispatch"}
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"pr_number", "proposal_sha", "purpose"}
    assert inputs["purpose"]["options"] == ["profile", "acceptance"]
    for forbidden in _FORBIDDEN_TEXT:
        assert forbidden not in text


def test_prepare_job_has_no_aws_authority():
    job = _load(_AWS_PLAN)["jobs"]["prepare"]
    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job
    assert "id-token" not in job["permissions"]
    script = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "python -m iac_agent.aws_plan prepare" in script


def test_plan_job_authority():
    workflow = _load(_AWS_PLAN)
    job = workflow["jobs"]["plan"]
    assert job["needs"] == "prepare"
    assert job["environment"] == "aws-plan"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    checkout = job["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] is False


def test_plan_job_verifies_handoff_before_credentials():
    steps = _load(_AWS_PLAN)["jobs"]["plan"]["steps"]
    markers = [_step_marker(step) for step in steps]
    positions = []
    for needle in (
        "v3-plan-handoff",
        "verify-handoff",
        "configure-aws-credentials",
        "iac_agent.aws_plan plan",
    ):
        matches = [index for index, marker in enumerate(markers) if needle in marker]
        assert matches, needle
        positions.append(matches[0])
    assert positions == sorted(positions)
    assert len(set(positions)) == 4


def test_credentials_step_is_not_always():
    steps = _load(_AWS_PLAN)["jobs"]["plan"]["steps"]
    credentials = next(
        step
        for step in steps
        if "configure-aws-credentials" in str(step.get("uses", ""))
    )
    assert "if" not in credentials
    always = [step for step in steps if step.get("if") == "always()"]
    assert len(always) == 1
    assert always[0]["with"]["name"] == "v3-plan-evidence"


def test_plan_job_does_not_fetch_the_proposal_sha():
    job = _load(_AWS_PLAN)["jobs"]["plan"]
    script = "\n".join(_step_marker(step) for step in job["steps"])
    assert "git fetch" not in script
    assert "git show" not in script
    credential = next(
        step for step in job["steps"] if "configure-aws-credentials" in str(step.get("uses", ""))
    )
    assert credential["with"]["role-to-assume"] == "arn:aws:iam::891377250201:role/IaCPlanRole"
    assert credential["with"]["aws-region"] == "us-east-1"
    assert credential["with"]["role-duration-seconds"] == 900

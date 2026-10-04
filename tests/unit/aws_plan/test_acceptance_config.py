"""Environment readiness is a payload check, not a workflow name."""

from __future__ import annotations

import json
from pathlib import Path

from iac_agent.aws_plan.__main__ import main
from iac_agent.aws_plan.acceptance import evaluate_environment

_WORKFLOW = Path(".github/workflows/aws-plan.yml")
_CI = Path(".github/workflows/ci.yml")


def _ready_payload() -> dict:
    return {
        "name": "aws-plan",
        "deployment_branch_policy": {"custom_branch_policies": ["main"]},
        "protection_rules": [{"type": "required_reviewers", "reviewers": [{"type": "User"}]}],
    }


def test_environment_check_requires_main_and_reviewers():
    assert evaluate_environment(_ready_payload()) == "ready"


def test_missing_environment_is_blocked():
    assert evaluate_environment(None) == "blocked"
    assert evaluate_environment({}) == "blocked"


def test_yaml_name_alone_is_not_enough():
    assert evaluate_environment({"name": "aws-plan"}) == "blocked"


def test_checker_is_not_wired_into_workflows():
    assert "check-environment" not in _WORKFLOW.read_text(encoding="utf-8")
    assert "check-environment" not in _CI.read_text(encoding="utf-8")


def test_cli_reads_a_payload_file(tmp_path: Path):
    ready = tmp_path / "ready.json"
    ready.write_text(json.dumps(_ready_payload()), encoding="utf-8")
    blocked = tmp_path / "blocked.json"
    blocked.write_text(json.dumps({"name": "aws-plan"}), encoding="utf-8")
    assert main(["check-environment", "--payload", str(ready)]) == 0
    assert main(["check-environment", "--payload", str(blocked)]) == 1

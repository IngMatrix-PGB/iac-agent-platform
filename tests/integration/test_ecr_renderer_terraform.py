"""Integration proof: ECR renderer output -> trusted module -> real Terraform plan.

Credential-free, matching tests/integration/test_s3_renderer_terraform.py.
Placeholder credentials only. Never a real AWS account. Never apply or destroy.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.ecr.renderer import EcrTerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "ecr"
_REPOSITORY_ADDRESS = "module.ecr.aws_ecr_repository.this"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=180)


def _plan(tmp_path: Path, spec: EcrResourceSpec, terraform_test_env, terraform_plan_env_overrides):
    workspace = tmp_path / "workspace"
    module_copy = tmp_path / "ecr"
    shutil.copytree(_TRUSTED_MODULE_DIR, module_copy)
    module_source = os.path.relpath(module_copy, start=workspace)
    composition = EcrTerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(workspace)

    fmt_check = _run(["terraform", "fmt", "-check", "-diff"], cwd=workspace, env=terraform_test_env)
    assert fmt_check.returncode == 0, (
        "renderer output is not canonically formatted:\n"
        f"stdout={fmt_check.stdout}\nstderr={fmt_check.stderr}"
    )

    init = _run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=workspace,
        env=terraform_test_env,
    )
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"
    _assert_no_aws_api_contact(init.stderr)

    validate = _run(
        ["terraform", "validate", "-no-color"], cwd=workspace, env=terraform_test_env
    )
    assert validate.returncode == 0, (
        f"terraform validate failed:\n{validate.stdout}\n{validate.stderr}"
    )
    _assert_no_aws_api_contact(validate.stderr)

    plan = _run(
        ["terraform", "plan", "-input=false", "-no-color", "-out=tfplan"],
        cwd=workspace,
        env=terraform_plan_env_overrides,
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"
    _assert_no_aws_api_contact(plan.stderr)

    show = _run(
        ["terraform", "show", "-json", "tfplan"], cwd=workspace, env=terraform_test_env
    )
    assert show.returncode == 0, f"terraform show -json failed:\n{show.stderr}"
    return json.loads(show.stdout)


def _assert_no_aws_api_contact(stderr: str) -> None:
    lowered = stderr.lower()
    for marker in ("amazonaws.com", "sts.", "169.254.169.254", "metadata.aws"):
        assert marker not in lowered, f"terraform attempted to contact AWS:\n{stderr}"


def _repository_change(plan_json: dict) -> dict:
    changes = plan_json["resource_changes"]
    assert len(changes) == 1, changes
    change = changes[0]
    assert change["address"] == _REPOSITORY_ADDRESS
    assert change["type"] == "aws_ecr_repository"
    assert change["change"]["actions"] == ["create"]
    addresses = [item["address"] for item in changes]
    for forbidden in ("lifecycle", "repository_policy", "kms"):
        assert not any(forbidden in address for address in addresses), addresses
    return change["change"]["after"]


def _first_block(after: dict, name: str) -> dict:
    block = after[name]
    assert isinstance(block, list) and len(block) == 1, after
    assert isinstance(block[0], dict)
    return block[0]


def test_secure_default_repository_plans_exactly_one_ecr_repository(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    plan_json = _plan(
        tmp_path,
        EcrResourceSpec(name="orders"),
        terraform_test_env,
        terraform_plan_env_overrides,
    )
    after = _repository_change(plan_json)
    assert after["name"] == "orders"
    assert after["image_tag_mutability"] == "IMMUTABLE"
    assert _first_block(after, "image_scanning_configuration")["scan_on_push"] is True
    encryption = _first_block(after, "encryption_configuration")
    assert encryption["encryption_type"] == "AES256"
    assert not encryption.get("kms_key")


def test_leading_digit_repository_name_is_accepted_by_the_provider(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    plan_json = _plan(
        tmp_path,
        EcrResourceSpec(name="1orders"),
        terraform_test_env,
        terraform_plan_env_overrides,
    )
    after = _repository_change(plan_json)
    assert after["name"] == "1orders"
    assert after["image_tag_mutability"] == "IMMUTABLE"

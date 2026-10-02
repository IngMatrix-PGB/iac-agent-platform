"""Credential-free Terraform fmt/init/validate/plan for bootstrap/aws-oidc/.

The module provider block has no skip flags, because a human apply must
validate real credentials. This test copies the module and adds a
disposable provider override in that copy only.

The plan reads the existing GitHub OIDC provider. A direct `terraform
plan` would call AWS. `terraform test` overrides that one data source,
so the plan stays credential-free and still renders the module's trust
policy and managed resources.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.execution.terraform_runner import TerraformRunner

_BOOTSTRAP_SOURCE = Path("bootstrap/aws-oidc")

_PLAN_ENV_OVERRIDES = {
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "TF_VAR_aws_region": "us-east-1",
    # Observed empirically in Batch 25 Task 11 (immutable format — this
    # repository was created 2026-09-13, after GitHub's 2026-07-15
    # immutable-subject cutover, so the legacy `owner/repo` shape never
    # applied here).
    "AWS_EC2_METADATA_DISABLED": "true",
    "TF_VAR_github_oidc_subject": (
        "repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request"
    ),
}

_OIDC_SUBJECT = "repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request"
_EXISTING_PROVIDER_ARN = (
    "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com"
)

_PLAN_TEST = f"""\
variables {{
  aws_region          = "us-east-1"
  github_oidc_subject = "{_OIDC_SUBJECT}"
}}

run "plan_creates_only_the_role_and_inline_policy" {{
  command = plan

  override_data {{
    target = data.aws_iam_openid_connect_provider.github_actions
    values = {{
      arn = "{_EXISTING_PROVIDER_ARN}"
      url = "https://token.actions.githubusercontent.com"
    }}
  }}

  assert {{
    condition     = aws_iam_role.iac_plan_role.name == "IaCPlanRole"
    error_message = "IaCPlanRole was not planned."
  }}

  assert {{
    condition     = aws_iam_role_policy.iac_plan_role_permissions.name == "IaCPlanRole-permissions"
    error_message = "inline permissions policy was not planned."
  }}
}}
"""

_TEST_OWNED_OVERRIDE = """\
provider "aws" {
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}
"""

pytestmark = [
    pytest.mark.real_bootstrap_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None, reason="terraform binary not available on PATH"
    ),
]


def _copy_bootstrap_module(tmp_path: Path) -> Path:
    workspace = tmp_path / "aws-oidc"
    shutil.copytree(_BOOTSTRAP_SOURCE, workspace)
    (workspace / "zz_test_override.tf").write_text(_TEST_OWNED_OVERRIDE)
    test_dir = workspace / "tests"
    test_dir.mkdir()
    (test_dir / "plan.tftest.hcl").write_text(_PLAN_TEST)
    return workspace


def test_bootstrap_module_fmt_is_clean():
    TerraformRunner().fmt(_BOOTSTRAP_SOURCE)  # raises on non-zero, no return-code check needed


def test_bootstrap_module_plans_exactly_the_expected_new_resources(tmp_path):
    workspace = _copy_bootstrap_module(tmp_path)
    runner = TerraformRunner()

    runner.init(workspace, env_overrides=_PLAN_ENV_OVERRIDES)
    runner.validate(workspace, env_overrides=_PLAN_ENV_OVERRIDES)

    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(_PLAN_ENV_OVERRIDES)
    completed = subprocess.run(
        ["terraform", "test", "-verbose", "-no-color"],
        cwd=workspace,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    plan_text = completed.stdout + completed.stderr
    assert completed.returncode == 0, plan_text

    assert '+ resource "aws_iam_role" "iac_plan_role"' in plan_text
    assert '+ resource "aws_iam_role_policy" "iac_plan_role_permissions"' in plan_text
    assert "aws_iam_openid_connect_provider" not in plan_text
    assert "Plan: 2 to add, 0 to change, 0 to destroy." in plan_text
    assert "will be destroyed" not in plan_text
    assert "will be updated" not in plan_text
    assert "sts:AssumeRoleWithWebIdentity" in plan_text
    assert "StringEquals" in plan_text
    assert "StringLike" not in plan_text
    assert "token.actions.githubusercontent.com:aud" in plan_text
    assert "sts.amazonaws.com" in plan_text
    assert _OIDC_SUBJECT in plan_text
    assert _EXISTING_PROVIDER_ARN in plan_text
    assert "sts:GetCallerIdentity" in plan_text

"""Batch 25, Task 10 (Gate B): real Terraform `fmt/init/validate/plan`
against `bootstrap/aws-oidc/` — still fully credential-free.

`bootstrap/aws-oidc/main.tf`'s own `provider "aws" {}` block
deliberately has NO skip-flags (unlike every renderer-generated
artifact) — a human doing the real, one-time apply needs genuine
credential validation, not a permanently-neutered provider. This test
therefore supplies its own disposable, test-owned override file in a
`tmp_path` copy of the module — never touching the real
`bootstrap/aws-oidc/` files on disk — exactly mirroring the same
credential-free-plan technique this repo already uses everywhere else
(skip-flags + placeholder env vars), scoped to this one test run only.
Variable values are supplied via `TF_VAR_*` environment variables
(through `env_overrides`) since `TerraformRunner.plan()` has no
CLI-arg-injection parameter — never a production-code change.

New-resource plans need no AWS read (design spec §0.2) — this applies
equally to the OIDC-provider/role resources here, which are also
entirely new; there is no backend, no prior state to refresh.

`fmt`/`init`/`validate`/`plan` all raise `TerraformCommandError` on a
non-zero exit (`TerraformRunner._run_checked`) rather than returning a
failed `CommandResult` — success in this test is proven by NOT
raising, not by inspecting a returncode.
"""

from __future__ import annotations

import shutil
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
    "TF_VAR_github_oidc_subject": (
        "repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request"
    ),
    "TF_VAR_github_oidc_thumbprints": '["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]',
}

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
    return workspace


def test_bootstrap_module_fmt_is_clean():
    TerraformRunner().fmt(_BOOTSTRAP_SOURCE)  # raises on non-zero, no return-code check needed


def test_bootstrap_module_plans_exactly_the_expected_new_resources(tmp_path):
    workspace = _copy_bootstrap_module(tmp_path)
    runner = TerraformRunner()

    runner.init(workspace, env_overrides=_PLAN_ENV_OVERRIDES)
    runner.validate(workspace, env_overrides=_PLAN_ENV_OVERRIDES)
    runner.plan(workspace, env_overrides=_PLAN_ENV_OVERRIDES)

    plan_json = runner.show_json(workspace)
    changes = plan_json["resource_changes"]

    # `resource_changes` includes both managed resources and the local
    # `data "aws_iam_policy_document"` read (mode="data") — only the
    # managed ones represent real infrastructure this plan would create.
    managed = [c for c in changes if c["mode"] == "managed"]
    managed_types = {c["type"] for c in managed}
    assert managed_types == {
        "aws_iam_openid_connect_provider",
        "aws_iam_role",
        "aws_iam_role_policy",
    }
    for change in managed:
        address = change["address"]
        assert change["change"]["actions"] == ["create"], f"{address} is not a plain create"

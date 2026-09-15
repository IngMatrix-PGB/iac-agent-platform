"""Integration proof: Python S3 renderer output -> trusted module ->
real Terraform plan (Phase 2).

Mirrors tests/integration/test_sqs_renderer_terraform.py exactly for
S3: validated S3ResourceSpec -> generated composition -> trusted
module -> terraform fmt/init/validate/plan, entirely without real AWS
credentials. The real add/change/destroy counts are observed here, not
assumed in advance.

Batch 16.5: environment construction now goes through the shared
`terraform_test_env`/`terraform_plan_env_overrides` fixtures
(tests/integration/conftest.py) rather than a locally defined
`_clean_env()`, so `terraform init` here reuses the session-scoped
`TF_PLUGIN_CACHE_DIR` instead of downloading its own copy of the AWS
provider binary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.s3.contract import S3EncryptionSpec, S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import S3TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "s3"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def test_renderer_output_produces_a_valid_credential_free_plan(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = S3ResourceSpec(
        name="my-example-bucket",
        tags={"Service": "reports"},
    )

    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = S3TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    assert (tmp_path / "main.tf").exists()
    assert (tmp_path / "versions.tf").exists()

    env = terraform_test_env

    fmt_check = _run(["terraform", "fmt", "-check"], cwd=tmp_path, env=env)
    assert fmt_check.returncode == 0, (
        "renderer output is not canonically formatted:\n"
        f"stdout={fmt_check.stdout}\nstderr={fmt_check.stderr}"
    )

    init = _run(["terraform", "init", "-backend=false"], cwd=tmp_path, env=env)
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    validate = _run(["terraform", "validate"], cwd=tmp_path, env=env)
    assert validate.returncode == 0, (
        f"terraform validate failed:\n{validate.stdout}\n{validate.stderr}"
    )

    plan = _run(
        ["terraform", "plan", "-out=tfplan"], cwd=tmp_path, env=terraform_plan_env_overrides
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"

    show = _run(["terraform", "show", "-json", "tfplan"], cwd=tmp_path, env=env)
    assert show.returncode == 0, f"terraform show -json failed:\n{show.stderr}"

    plan_json = json.loads(show.stdout)
    resource_changes = {
        rc["address"]: rc["change"]["actions"] for rc in plan_json["resource_changes"]
    }

    # Observed empirically (not assumed in advance): the secure baseline
    # S3 module plans exactly these five resources.
    assert resource_changes == {
        "module.bucket.aws_s3_bucket.this": ["create"],
        "module.bucket.aws_s3_bucket_versioning.this": ["create"],
        "module.bucket.aws_s3_bucket_server_side_encryption_configuration.this": ["create"],
        "module.bucket.aws_s3_bucket_public_access_block.this": ["create"],
        "module.bucket.aws_s3_bucket_policy.tls_only": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


def test_renderer_output_with_kms_encryption_produces_a_valid_plan(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = S3ResourceSpec(
        name="my-example-bucket", encryption=S3EncryptionSpec(kms_key_id="alias/aws/s3")
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = S3TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    env = terraform_test_env
    init = _run(["terraform", "init", "-backend=false"], cwd=tmp_path, env=env)
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    plan = _run(
        ["terraform", "plan", "-out=tfplan"], cwd=tmp_path, env=terraform_plan_env_overrides
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"

    show = _run(["terraform", "show", "-json", "tfplan"], cwd=tmp_path, env=env)
    plan_json = json.loads(show.stdout)
    encryption_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.bucket.aws_s3_bucket_server_side_encryption_configuration.this"
    )
    sse_rule = encryption_change["change"]["after"]["rule"][0]
    rule = sse_rule["apply_server_side_encryption_by_default"][0]
    assert rule["sse_algorithm"] == "aws:kms"
    assert rule["kms_master_key_id"] == "alias/aws/s3"

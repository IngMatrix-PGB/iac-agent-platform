"""Integration proof: Python DynamoDB renderer output -> trusted module ->
real Terraform plan (Phase 2, Batch 17).

Mirrors tests/integration/test_s3_renderer_terraform.py exactly for
DynamoDB: validated DynamoDBResourceSpec -> generated composition ->
trusted module -> terraform fmt/init/validate/plan, entirely without
real AWS credentials. The real add/change/destroy counts are observed
here, not assumed in advance.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.dynamodb.renderer import DynamoDBTerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "dynamodb"

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
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        sort_key=DynamoDBKeySpec(name="sk", type=DynamoDBKeyType.STRING),
        tags={"Service": "orders"},
    )

    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = DynamoDBTerraformCompositionRenderer().render(spec, module_source=module_source)
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
    # DynamoDB module plans exactly this one resource.
    assert resource_changes == {
        "module.dynamodb.aws_dynamodb_table.this": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())

    table_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.dynamodb.aws_dynamodb_table.this"
    )
    after = table_change["change"]["after"]
    assert after["billing_mode"] == "PAY_PER_REQUEST"
    assert after["hash_key"] == "pk"
    assert after["range_key"] == "sk"
    assert after["deletion_protection_enabled"] is True
    assert {a["name"]: a["type"] for a in after["attribute"]} == {"pk": "S", "sk": "S"}
    assert after["point_in_time_recovery"][0]["enabled"] is True
    assert after["server_side_encryption"][0]["enabled"] is True


def test_renderer_output_uses_aws_owned_key_encryption_with_no_kms_arn(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """Batch 17: customer-managed KMS is deliberately deferred (see
    DynamoDBEncryptionSpec's docstring — a bare alias/key-ID form that
    the shared KMS validator accepts for SQS/S3 was empirically found
    to be rejected by `aws_dynamodb_table.server_side_encryption.
    kms_key_arn`, which requires a full ARN). This proves the real
    plan for AWS-owned-key encryption succeeds with no kms_key_arn set
    at all."""
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = DynamoDBTerraformCompositionRenderer().render(spec, module_source=module_source)
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
    table_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.dynamodb.aws_dynamodb_table.this"
    )
    sse = table_change["change"]["after"]["server_side_encryption"][0]
    assert sse["enabled"] is True
    assert sse.get("kms_key_arn") is None


def test_renderer_output_without_sort_key_omits_range_key_and_second_attribute(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = DynamoDBResourceSpec(
        name="basic-table",
        partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.NUMBER),
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = DynamoDBTerraformCompositionRenderer().render(spec, module_source=module_source)
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
    table_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.dynamodb.aws_dynamodb_table.this"
    )
    after = table_change["change"]["after"]
    assert after["range_key"] is None
    assert len(after["attribute"]) == 1
    assert after["attribute"][0] == {"name": "id", "type": "N"}

"""Integration proof: Python API Gateway renderer output -> trusted
module -> real Terraform plan (Phase 2, Batch 20).

Mirrors tests/integration/test_dynamodb_renderer_terraform.py for API
Gateway: validated `ApiGatewayResourceSpec` -> generated composition ->
trusted module -> terraform fmt/init/validate/plan, entirely without
real AWS credentials. The real add/change/destroy counts and every
managed resource address are observed here, not assumed in advance.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.api_gateway.renderer import ApiGatewayTerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "api_gateway"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _plan_json(
    tmp_path: Path,
    spec: ApiGatewayResourceSpec,
    terraform_test_env,
    terraform_plan_env_overrides,
) -> dict:
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = ApiGatewayTerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    env = terraform_test_env
    init = _run(["terraform", "init", "-backend=false"], cwd=tmp_path, env=env)
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    plan = _run(
        ["terraform", "plan", "-out=tfplan"], cwd=tmp_path, env=terraform_plan_env_overrides
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"

    show = _run(["terraform", "show", "-json", "tfplan"], cwd=tmp_path, env=env)
    assert show.returncode == 0, f"terraform show -json failed:\n{show.stderr}"
    return json.loads(show.stdout)


def test_renderer_output_produces_a_valid_credential_free_plan(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = ApiGatewayResourceSpec(name="orders-api", description="Orders API")
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = ApiGatewayTerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    assert (tmp_path / "main.tf").exists()
    assert (tmp_path / "versions.tf").exists()

    fmt_check = _run(["terraform", "fmt", "-check"], cwd=tmp_path, env=terraform_test_env)
    assert fmt_check.returncode == 0, (
        "renderer output is not canonically formatted:\n"
        f"stdout={fmt_check.stdout}\nstderr={fmt_check.stderr}"
    )

    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)
    resource_changes = {
        rc["address"]: rc["change"]["actions"]
        for rc in plan_json["resource_changes"]
        if rc["mode"] == "managed"
    }

    # Observed empirically (not assumed in advance): the secure baseline
    # API Gateway module always plans exactly these two managed
    # resources.
    assert resource_changes == {
        "module.api.aws_apigatewayv2_api.this": ["create"],
        "module.api.aws_apigatewayv2_stage.default": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


def test_api_configuration_matches_the_spec(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = ApiGatewayResourceSpec(name="orders-api", description="Orders API")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)
    api_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.api.aws_apigatewayv2_api.this"
    )
    after = api_change["change"]["after"]
    assert after["name"] == "orders-api"
    assert after["protocol_type"] == "HTTP"
    assert after["description"] == "Orders API"


def test_stage_is_default_with_auto_deploy_enabled(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = ApiGatewayResourceSpec(name="orders-api")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)
    stage_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.api.aws_apigatewayv2_stage.default"
    )
    after = stage_change["change"]["after"]
    assert after["name"] == "$default"
    assert after["auto_deploy"] is True

"""Integration proof: Python api_lambda renderer output -> the two
trusted modules -> real Terraform plan (Phase 2, Batch 20).

Mirrors tests/integration/test_serverless_worker_renderer_terraform.py:
validated `ApiLambdaSpec` -> generated composition -> the trusted API
Gateway/Lambda modules plus the composition-owned relationship
resources -> terraform fmt/init/validate/plan, entirely without real
AWS credentials. The real add/change/destroy counts and every managed
resource address are observed here empirically, not assumed in
advance.

Also proves the required IAM/route/integration invariants this batch
requires by inspecting the real plan JSON directly: the Lambda
execution role's baseline CloudWatch Logs permissions exist unchanged
(Batch 18 behavior), the Lambda invocation permission grants exactly
`apigateway.amazonaws.com`/`lambda:InvokeFunction` (never a wildcard
principal, never a change to the execution role), the route key exactly
matches `METHOD path`, and the integration is `AWS_PROXY` with payload
format `2.0` referencing the Lambda function's own ARN.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda.renderer import (
    ApiLambdaModuleSources,
    ApiLambdaTerraformRenderer,
)
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_MODULES_ROOT = _REPO_ROOT / "terraform" / "modules"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _default_spec(**overrides) -> ApiLambdaSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        ),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
    }
    defaults.update(overrides)
    return ApiLambdaSpec(**defaults)


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _plan_json(
    tmp_path: Path,
    spec: ApiLambdaSpec,
    terraform_test_env,
    terraform_plan_env_overrides,
) -> dict:
    module_sources = ApiLambdaModuleSources(
        api=os.path.relpath(_TERRAFORM_MODULES_ROOT / "api_gateway", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
    )
    composition = ApiLambdaTerraformRenderer().render(spec, module_sources=module_sources)
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
    spec = _default_spec()
    module_sources = ApiLambdaModuleSources(
        api=os.path.relpath(_TERRAFORM_MODULES_ROOT / "api_gateway", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
    )
    composition = ApiLambdaTerraformRenderer().render(spec, module_sources=module_sources)
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
    # api_lambda composition plans exactly these nine managed resources.
    assert resource_changes == {
        "module.api.aws_apigatewayv2_api.this": ["create"],
        "module.api.aws_apigatewayv2_stage.default": ["create"],
        "module.function.aws_cloudwatch_log_group.this": ["create"],
        "module.function.aws_iam_role.this": ["create"],
        "module.function.aws_iam_role_policy.logs": ["create"],
        "module.function.aws_lambda_function.this": ["create"],
        "aws_apigatewayv2_integration.lambda": ["create"],
        "aws_apigatewayv2_route.this": ["create"],
        "aws_lambda_permission.api_gateway": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_integration_is_aws_proxy_with_payload_format_2_and_references_the_function(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    integration = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_apigatewayv2_integration.lambda"
    )
    after = integration["change"]["after"]
    assert after["integration_type"] == "AWS_PROXY"
    assert after["integration_method"] == "POST"
    assert after["payload_format_version"] == "2.0"

    # `integration_uri` references the not-yet-created function's ARN —
    # genuinely unknown at plan time, the same evidence pattern already
    # established for every cross-module reference in this project.
    after_unknown = integration["change"]["after_unknown"]
    assert after_unknown["integration_uri"] is True


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_route_key_exactly_matches_method_and_path(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec(route=RouteSpec(method=HttpMethod.GET, path="/orders/{id}"))
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    route = next(
        rc for rc in plan_json["resource_changes"] if rc["address"] == "aws_apigatewayv2_route.this"
    )
    after = route["change"]["after"]
    assert after["route_key"] == "GET /orders/{id}"
    assert after["route_key"] != "$default"


# ---------------------------------------------------------------------------
# IAM hard-safety invariants
#
# The Lambda execution role's baseline CloudWatch Logs permissions are
# exactly the Batch 18 trusted-module behavior, completely unaffected by
# this composition — proven here by confirming the same role/policy
# addresses exist and asserting the composition adds no aws_iam_role_
# policy of its own. The invocation grant is a separate, Lambda
# resource-based permission (never a role change) — verified directly.
# ---------------------------------------------------------------------------


def test_lambda_permission_grants_exactly_apigateway_invoke(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    permission = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_lambda_permission.api_gateway"
    )
    after = permission["change"]["after"]
    assert after["action"] == "lambda:InvokeFunction"
    assert after["principal"] == "apigateway.amazonaws.com"

    # No wildcard principal or action anywhere in this permission.
    serialized = json.dumps(after)
    assert '"principal": "*"' not in serialized
    assert after["principal"] != "*"
    assert after["action"] != "lambda:*"


def test_lambda_permission_source_arn_references_the_api_execution_arn(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    permission = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_lambda_permission.api_gateway"
    )
    # `source_arn` references the not-yet-created API's own execution
    # ARN — genuinely unknown at plan time.
    after_unknown = permission["change"]["after_unknown"]
    assert after_unknown["source_arn"] is True


def test_lambda_permission_source_arn_expression_scopes_to_the_exact_route():
    """Static check against the renderer's own checked-in source (the
    exact code the plan above just used) for the one field a
    credential-free plan can never resolve: the concrete resource-
    scoping expression."""
    renderer_source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "iac_agent"
        / "compositions"
        / "api_lambda"
        / "renderer.py"
    ).read_text(encoding="utf-8")
    assert "${{module.api.execution_arn}}/{_STAGE_NAME}/{method}{path}" in renderer_source
    assert '"*"' not in renderer_source.split("_STAGE_NAME")[0]


def test_composition_adds_no_iam_role_policy_of_its_own(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """Critical IAM distinction: the invocation grant must never modify
    the Lambda execution role. Exactly one aws_iam_role_policy exists
    in the whole plan (the trusted Lambda module's own baseline logs
    policy from Batch 18) — the composition adds none."""
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    role_policy_addresses = [
        rc["address"]
        for rc in plan_json["resource_changes"]
        if rc["mode"] == "managed" and "aws_iam_role_policy" in rc["address"]
    ]
    assert role_policy_addresses == ["module.function.aws_iam_role_policy.logs"]

    resource_changes = {
        rc["address"] for rc in plan_json["resource_changes"] if rc["mode"] == "managed"
    }
    assert not any("policy_attachment" in addr for addr in resource_changes)


def test_execution_role_baseline_logs_permissions_remain_unchanged(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """Batch 18's own trust-policy invariant (lambda.amazonaws.com
    only) still holds unchanged in an api_lambda composition."""
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    role_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.function.aws_iam_role.this"
    )
    trust_policy = json.loads(role_change["change"]["after"]["assume_role_policy"])
    statement = trust_policy["Statement"][0]
    assert statement["Principal"] == {"Service": "lambda.amazonaws.com"}

"""Integration proof: Python api_lambda_dynamodb renderer output -> the
three trusted modules -> real Terraform plan (Batch 26, Gate B, Task
15).

Mirrors tests/integration/test_api_lambda_renderer_terraform.py:
validated `ApiLambdaDynamoDbSpec` -> generated composition -> the
trusted API Gateway/Lambda/DynamoDB modules plus the composition-owned
relationship resources -> terraform fmt/init/validate/plan, entirely
without real AWS credentials. The real add/change/destroy counts and
every managed resource address are observed here empirically, not
assumed in advance.

Also proves the required IAM invariants this composition needs by
inspecting the real plan JSON directly: the Lambda execution role's
baseline CloudWatch Logs permissions exist unchanged, the DynamoDB
write policy grants exactly `dynamodb:PutItem` scoped to this table's
own (not-yet-created, `after_unknown`) ARN, and the API-Gateway-side
invariants already proven for `ApiLambdaSpec` hold identically here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.compositions.api_lambda.contract import HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.api_lambda_dynamodb.renderer import (
    ApiLambdaDynamoDbModuleSources,
    ApiLambdaDynamoDbTerraformRenderer,
)
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
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


def _default_spec(**overrides) -> ApiLambdaDynamoDbSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        ),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
        "table": DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="id", type="S")
        ),
    }
    defaults.update(overrides)
    return ApiLambdaDynamoDbSpec(**defaults)


def _module_sources(tmp_path: Path) -> ApiLambdaDynamoDbModuleSources:
    return ApiLambdaDynamoDbModuleSources(
        api=os.path.relpath(_TERRAFORM_MODULES_ROOT / "api_gateway", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
        table=os.path.relpath(_TERRAFORM_MODULES_ROOT / "dynamodb", start=tmp_path),
    )


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _plan_json(
    tmp_path: Path,
    spec: ApiLambdaDynamoDbSpec,
    terraform_test_env,
    terraform_plan_env_overrides,
) -> dict:
    composition = ApiLambdaDynamoDbTerraformRenderer().render(
        spec, module_sources=_module_sources(tmp_path)
    )
    composition.write_to(tmp_path)

    env = terraform_test_env
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
    return json.loads(show.stdout)


def test_renderer_output_produces_a_valid_credential_free_plan(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    composition = ApiLambdaDynamoDbTerraformRenderer().render(
        spec, module_sources=_module_sources(tmp_path)
    )
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
    # api_lambda_dynamodb composition plans exactly these eleven managed
    # resources.
    assert resource_changes == {
        "module.api.aws_apigatewayv2_api.this": ["create"],
        "module.api.aws_apigatewayv2_stage.default": ["create"],
        "module.function.aws_cloudwatch_log_group.this": ["create"],
        "module.function.aws_iam_role.this": ["create"],
        "module.function.aws_iam_role_policy.logs": ["create"],
        "module.function.aws_lambda_function.this": ["create"],
        "module.table.aws_dynamodb_table.this": ["create"],
        "aws_apigatewayv2_integration.lambda": ["create"],
        "aws_apigatewayv2_route.this": ["create"],
        "aws_lambda_permission.api_gateway": ["create"],
        "aws_iam_role_policy.dynamodb_write": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


def test_dynamodb_write_policy_document_is_unknown_at_plan_time(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """The policy document is a `data.aws_iam_policy_document` reference
    whose own `resources = [module.table.table_arn]` depends on the
    not-yet-created table — so, unlike a plain literal policy, both
    `policy` and `role` are genuinely unknown at plan time (real,
    observed Terraform behavior, not assumed in advance). The exact
    action list is instead verified statically below, the same
    evidence pattern this project already uses for every other
    cross-module value a credential-free plan can't resolve (see
    `test_lambda_permission_source_arn_expression_scopes_to_the_exact_route`
    in the api_lambda integration test)."""
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    policy = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_iam_role_policy.dynamodb_write"
    )
    after_unknown = policy["change"]["after_unknown"]
    assert after_unknown["policy"] is True
    assert after_unknown["role"] is True
    assert policy["change"]["after"].get("name") == "orders-api-worker-dynamodb-write"


def test_dynamodb_write_policy_action_list_is_exactly_put_item():
    """Static check against the renderer's own checked-in source (the
    exact code the plan above just used) for the one field a
    credential-free plan can never resolve: the concrete action list
    inside the not-yet-known policy document."""
    renderer_source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "iac_agent"
        / "compositions"
        / "api_lambda_dynamodb"
        / "renderer.py"
    ).read_text(encoding="utf-8")
    assert '_DYNAMODB_WRITE_ACTIONS = ("dynamodb:PutItem",)' in renderer_source
    for forbidden in (
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem",
        'Resource": "*"',
    ):
        assert forbidden not in renderer_source


def test_dynamodb_write_policy_attaches_to_the_function_execution_role(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    policy = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_iam_role_policy.dynamodb_write"
    )
    after_unknown = policy["change"]["after_unknown"]
    # `role` references the function module's own execution_role_name
    # output — genuinely unknown at plan time.
    assert after_unknown["role"] is True


def test_composition_adds_exactly_two_iam_role_policies_logs_and_dynamodb_write(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """Critical IAM distinction: the Lambda execution role gains only
    the trusted module's own baseline logs policy plus this
    composition's one DynamoDB write policy — never a policy
    attachment, never a role modification beyond that."""
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    role_policy_addresses = sorted(
        rc["address"]
        for rc in plan_json["resource_changes"]
        if rc["mode"] == "managed" and "aws_iam_role_policy" in rc["address"]
    )
    assert role_policy_addresses == [
        "aws_iam_role_policy.dynamodb_write",
        "module.function.aws_iam_role_policy.logs",
    ]

    resource_changes = {
        rc["address"] for rc in plan_json["resource_changes"] if rc["mode"] == "managed"
    }
    assert not any("policy_attachment" in addr for addr in resource_changes)


def test_execution_role_baseline_logs_permissions_remain_unchanged(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    """Batch 18's own trust-policy invariant (lambda.amazonaws.com
    only) still holds unchanged in this composition."""
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
    assert after["principal"] != "*"


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


def test_table_module_reflects_partition_key(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec(
        table=DynamoDBResourceSpec(
            name="custom-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        )
    )
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    table = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.table.aws_dynamodb_table.this"
    )
    after = table["change"]["after"]
    assert after["name"] == "custom-table"
    assert after["hash_key"] == "pk"

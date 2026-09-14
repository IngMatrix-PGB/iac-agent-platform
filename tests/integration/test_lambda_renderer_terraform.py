"""Integration proof: Python Lambda renderer output -> trusted module ->
real Terraform plan (Phase 2, Batch 18).

Mirrors tests/integration/test_dynamodb_renderer_terraform.py for
Lambda: validated LambdaResourceSpec -> generated composition ->
trusted module -> terraform fmt/init/validate/plan, entirely without
real AWS credentials. The real add/change/destroy counts and every
managed resource address are observed here, not assumed in advance.

Also proves the IAM hard-safety invariants this batch requires by
inspecting the real plan JSON directly: the execution role's trust
policy allows only `lambda.amazonaws.com`, the inline permission policy
grants only the three documented CloudWatch Logs actions scoped to this
function's own log group, and neither policy ever contains a wildcard
principal, an `iam:*`/`*` action, or a permission for any other AWS
resource type this platform supports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.lambda_function.renderer import LambdaTerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "lambda"

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
    tmp_path: Path, spec: LambdaResourceSpec, terraform_test_env, terraform_plan_env_overrides
) -> dict:
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = LambdaTerraformCompositionRenderer().render(spec, module_source=module_source)
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
    spec = LambdaResourceSpec(
        name="orders-processor",
        handler="app.handler",
        environment_variables={"LOG_LEVEL": "INFO"},
        tags={"Service": "orders"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = LambdaTerraformCompositionRenderer().render(spec, module_source=module_source)
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
    # Lambda+IAM module plans exactly these four managed resources.
    assert resource_changes == {
        "module.lambda.aws_cloudwatch_log_group.this": ["create"],
        "module.lambda.aws_iam_role.this": ["create"],
        "module.lambda.aws_iam_role_policy.logs": ["create"],
        "module.lambda.aws_lambda_function.this": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


def test_lambda_function_configuration_matches_the_spec(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(
        name="orders-processor",
        handler="app.handler",
        memory_size_mb=512,
        timeout_seconds=60,
        reserved_concurrency=5,
    )
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)
    function_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.lambda.aws_lambda_function.this"
    )
    after = function_change["change"]["after"]

    assert after["function_name"] == "orders-processor"
    assert after["handler"] == "app.handler"
    assert after["runtime"] == "python3.12"
    assert after["architectures"] == ["arm64"]
    assert after["memory_size"] == 512
    assert after["timeout"] == 60
    assert after["reserved_concurrent_executions"] == 5
    assert after["tracing_config"][0]["mode"] == "Active"
    # The AWS provider omits the `environment` block entirely from the
    # plan when `variables` is empty, rather than representing it as
    # `[{"variables": {}}]` — verified empirically rather than assumed.
    assert after["environment"] in ([], [{"variables": {}}])


def test_log_group_uses_the_conventional_name_and_configured_retention(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler", log_retention_days=90)
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)
    log_group_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.lambda.aws_cloudwatch_log_group.this"
    )
    after = log_group_change["change"]["after"]
    assert after["name"] == "/aws/lambda/orders-processor"
    assert after["retention_in_days"] == 90


# ---------------------------------------------------------------------------
# IAM hard-safety invariants
#
# The trust policy (`data.aws_iam_policy_document.assume_role`) has no
# dependency on any not-yet-created resource, so its resolved JSON is
# fully known even in a credential-free plan — verified empirically,
# and read here straight off `aws_iam_role.this.assume_role_policy` in
# the real plan JSON (not the `planned_values` data-source listing,
# which does not carry this particular data source at all).
#
# The logs policy (`data.aws_iam_policy_document.logs`), by contrast,
# references `aws_cloudwatch_log_group.this.arn` — a real AWS-assigned
# value Terraform cannot know without a real account, so its `Resource`
# is genuinely `(known after apply)` in ANY credential-free plan.
# Verified empirically via `after_unknown` before writing these
# assertions, rather than assumed. This is real, useful evidence in
# itself (a hardcoded "*" would show as a KNOWN literal, not an unknown
# computed reference) — combined with a direct read of the trusted
# module's own checked-in `main.tf` (the exact file this very plan just
# used) for the concrete resource-scoping expression, which is safe to
# assert on statically because it is deterministic, version-controlled
# input, not the plan's output.
# ---------------------------------------------------------------------------


def test_execution_role_trust_policy_allows_only_lambda_service_principal(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    role_change = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.lambda.aws_iam_role.this"
    )
    trust_policy = json.loads(role_change["change"]["after"]["assume_role_policy"])

    statements = trust_policy["Statement"]
    assert len(statements) == 1

    statement = statements[0]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == "sts:AssumeRole"
    assert statement["Principal"] == {"Service": "lambda.amazonaws.com"}

    # No wildcard principal in any form.
    serialized = json.dumps(trust_policy)
    assert '"Principal": "*"' not in serialized
    assert '"AWS": "*"' not in serialized
    assert '"AWS":"*"' not in serialized.replace(" ", "")


def test_logs_policy_grants_only_the_three_baseline_actions(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    logs_data_source = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.lambda.data.aws_iam_policy_document.logs"
    )
    statement = logs_data_source["change"]["after"]["statement"][0]

    assert statement["effect"] == "Allow"
    assert statement["not_actions"] is None
    assert set(statement["actions"]) == {
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    }

    # `resources` is the one field that genuinely cannot be resolved
    # without a real AWS account (it references the log group's
    # AWS-assigned ARN) — its presence as exactly one *unknown* entry,
    # rather than a known literal, is itself evidence it is not a
    # hardcoded wildcard.
    after_unknown = logs_data_source["change"]["after_unknown"]["statement"][0]
    assert len(statement["resources"]) == 1
    assert after_unknown["resources"] == [True]


def test_logs_policy_resource_scoping_is_this_functions_own_log_group_not_a_wildcard():
    """Static check against the trusted module's own checked-in source
    (the exact file the plan above just used) for the one field a
    credential-free plan can never resolve: the concrete resource
    scoping expression."""
    main_tf = (_TRUSTED_MODULE_DIR / "main.tf").read_text(encoding="utf-8")

    assert 'resources = ["${aws_cloudwatch_log_group.this.arn}:*"]' in main_tf
    assert 'resources = ["*"]' not in main_tf


def test_logs_policy_never_grants_iam_wildcard_or_unrelated_resource_permissions(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    logs_data_source = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "module.lambda.data.aws_iam_policy_document.logs"
    )
    serialized = json.dumps(logs_data_source["change"]["after"])

    # No administrator/wildcard action anywhere.
    assert '"actions": ["*"]' not in serialized
    assert "iam:*" not in serialized

    # No permissions for any other AWS resource type this platform
    # supports — Batch 18 proves Lambda baseline isolation only.
    for forbidden_prefix in ("sqs:", "s3:", "dynamodb:"):
        assert forbidden_prefix not in serialized


def test_execution_role_has_no_managed_administrator_policy_attached(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler")
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    resource_changes = {
        rc["address"]: rc for rc in plan_json["resource_changes"] if rc["mode"] == "managed"
    }
    # No aws_iam_role_policy_attachment / aws_iam_policy resource at all
    # — only the one narrow inline aws_iam_role_policy this module owns.
    assert not any("policy_attachment" in addr for addr in resource_changes)
    role_change = resource_changes["module.lambda.aws_iam_role.this"]
    assert role_change["change"]["after"].get("managed_policy_arns") in (None, [])

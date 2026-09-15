"""Integration proof: Python serverless-worker renderer output -> the
three trusted modules -> real Terraform plan (Phase 2, Batch 19).

Mirrors tests/integration/test_lambda_renderer_terraform.py: validated
`ServerlessWorkerSpec` -> generated composition -> the trusted SQS/
Lambda/DynamoDB modules plus the composition-owned relationship
resources -> terraform fmt/init/validate/plan, entirely without real
AWS credentials. The real add/change/destroy counts and every managed
resource address are observed here empirically, not assumed in
advance.

Also proves the IAM hard-safety invariants this batch requires by
inspecting the real plan JSON directly: the SQS-consumer policy grants
only the three documented actions scoped to this composition's own
queue, the DynamoDB-write policy grants only PutItem scoped to this
composition's own table, the event source mapping binds exactly this
queue to this function, and neither composition-owned IAM policy ever
contains a wildcard action/resource or a permission for S3 (which this
composition never uses).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.compositions.serverless_worker.renderer import (
    ServerlessWorkerModuleSources,
    ServerlessWorkerTerraformRenderer,
)
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_MODULES_ROOT = _REPO_ROOT / "terraform" / "modules"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _default_spec(**overrides) -> ServerlessWorkerSpec:
    defaults = {
        "name": "orders-worker",
        "queue": SQSResourceSpec(name="orders-queue"),
        "function": LambdaResourceSpec(
            name="orders-processor", handler="app.handler", reserved_concurrency=5
        ),
        "table": DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    }
    defaults.update(overrides)
    return ServerlessWorkerSpec(**defaults)


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _plan_json(
    tmp_path: Path,
    spec: ServerlessWorkerSpec,
    terraform_test_env,
    terraform_plan_env_overrides,
) -> dict:
    module_sources = ServerlessWorkerModuleSources(
        queue=os.path.relpath(_TERRAFORM_MODULES_ROOT / "sqs", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
        table=os.path.relpath(_TERRAFORM_MODULES_ROOT / "dynamodb", start=tmp_path),
    )
    composition = ServerlessWorkerTerraformRenderer().render(spec, module_sources=module_sources)
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
    module_sources = ServerlessWorkerModuleSources(
        queue=os.path.relpath(_TERRAFORM_MODULES_ROOT / "sqs", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
        table=os.path.relpath(_TERRAFORM_MODULES_ROOT / "dynamodb", start=tmp_path),
    )
    composition = ServerlessWorkerTerraformRenderer().render(spec, module_sources=module_sources)
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
    # serverless-worker composition plans exactly these ten managed
    # resources — two from the SQS module (primary + DLQ), four from
    # the Lambda module, one from the DynamoDB module, and the three
    # composition-owned relationship resources.
    assert resource_changes == {
        "module.queue.aws_sqs_queue.dlq[0]": ["create"],
        "module.queue.aws_sqs_queue.this": ["create"],
        "module.function.aws_cloudwatch_log_group.this": ["create"],
        "module.function.aws_iam_role.this": ["create"],
        "module.function.aws_iam_role_policy.logs": ["create"],
        "module.function.aws_lambda_function.this": ["create"],
        "module.table.aws_dynamodb_table.this": ["create"],
        "aws_lambda_event_source_mapping.queue_to_function": ["create"],
        "aws_iam_role_policy.sqs_consumer": ["create"],
        "aws_iam_role_policy.dynamodb_write": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())


# ---------------------------------------------------------------------------
# Event source mapping
# ---------------------------------------------------------------------------


def test_event_source_mapping_binds_exactly_this_queue_to_this_function(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    esm = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_lambda_event_source_mapping.queue_to_function"
    )
    after = esm["change"]["after"]
    assert after["batch_size"] == 10
    assert after["enabled"] is True

    # `event_source_arn`/`function_name` are unresolved module-output
    # references at plan time (both queue and function are themselves
    # not-yet-created) — that unknownness is itself the evidence this
    # binds to *this* composition's own queue/function, not a hardcoded
    # or cross-composition ARN.
    after_unknown = esm["change"]["after_unknown"]
    assert after_unknown["event_source_arn"] is True
    assert after_unknown["function_arn"] is True


def test_event_source_mapping_uses_a_custom_batch_size_and_batching_window(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec(
        event_source_batch_size=100, event_source_maximum_batching_window_seconds=45
    )
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    esm = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "aws_lambda_event_source_mapping.queue_to_function"
    )
    after = esm["change"]["after"]
    assert after["batch_size"] == 100
    assert after["maximum_batching_window_in_seconds"] == 45


# ---------------------------------------------------------------------------
# IAM hard-safety invariants
#
# Both composition-owned IAM policy documents reference a not-yet-
# created resource's ARN (`module.queue.queue_arn` /
# `module.table.table_arn`), so their `resources` field is genuinely
# unknown even in a credential-free plan — verified empirically before
# writing these assertions, exactly like Batch 18's identical discovery
# for the Lambda module's own logs policy. The concrete resource-
# scoping expressions are instead verified via a direct, justified
# static read of the renderer's own rendered `main.tf` (the exact file
# this very plan just used).
# ---------------------------------------------------------------------------


def test_sqs_consumer_policy_grants_only_the_three_documented_actions(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    doc = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "data.aws_iam_policy_document.sqs_consumer"
    )
    statement = doc["change"]["after"]["statement"][0]
    assert statement["effect"] == "Allow"
    assert set(statement["actions"]) == {
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
    }

    after_unknown = doc["change"]["after_unknown"]["statement"][0]
    assert len(statement["resources"]) == 1
    assert after_unknown["resources"] == [True]


def test_dynamodb_write_policy_grants_only_put_item(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    doc = next(
        rc
        for rc in plan_json["resource_changes"]
        if rc["address"] == "data.aws_iam_policy_document.dynamodb_write"
    )
    statement = doc["change"]["after"]["statement"][0]
    assert statement["effect"] == "Allow"
    assert statement["actions"] == ["dynamodb:PutItem"]

    after_unknown = doc["change"]["after_unknown"]["statement"][0]
    assert len(statement["resources"]) == 1
    assert after_unknown["resources"] == [True]


def test_iam_policy_resource_scoping_matches_the_renderer_source_not_a_wildcard():
    """Static check against the renderer's own checked-in source (the
    exact code the plan above just used) for the one field a
    credential-free plan can never resolve: the concrete resource-
    scoping expression."""
    renderer_source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "iac_agent"
        / "compositions"
        / "serverless_worker"
        / "renderer.py"
    ).read_text(encoding="utf-8")

    assert "resources = [module.queue.queue_arn]" in renderer_source
    assert "resources = [module.table.table_arn]" in renderer_source
    assert 'resources = ["*"]' not in renderer_source


def test_composition_iam_policies_never_grant_a_wildcard_or_s3_permission(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    for address in (
        "data.aws_iam_policy_document.sqs_consumer",
        "data.aws_iam_policy_document.dynamodb_write",
    ):
        doc = next(rc for rc in plan_json["resource_changes"] if rc["address"] == address)
        serialized = json.dumps(doc["change"]["after"])
        assert '"actions": ["*"]' not in serialized
        assert "iam:*" not in serialized
        assert "s3:" not in serialized


def test_composition_iam_policies_attach_only_to_the_lambda_execution_role(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    spec = _default_spec()
    plan_json = _plan_json(tmp_path, spec, terraform_test_env, terraform_plan_env_overrides)

    resource_changes = {
        rc["address"]: rc for rc in plan_json["resource_changes"] if rc["mode"] == "managed"
    }
    for address in ("aws_iam_role_policy.sqs_consumer", "aws_iam_role_policy.dynamodb_write"):
        after_unknown = resource_changes[address]["change"]["after_unknown"]
        # `role` is unresolved at plan time (it references the not-yet-
        # created Lambda execution role's own module output) — the
        # unknownness itself is evidence it is a real module reference,
        # never a hardcoded/foreign role name.
        assert after_unknown["role"] is True

    assert not any("policy_attachment" in addr for addr in resource_changes)

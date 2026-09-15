"""Unit tests for composition-level platform policies (Batches 19-20).

Mirrors tests/unit/policies/test_lambda_platform_policies.py in
discipline: exercises `evaluate_composition_policies` as a pure
function of an already-validated composition spec (`ServerlessWorkerSpec`
or `ApiLambdaSpec`) and a `PlanSummary`, never real Terraform or Checkov.
"""

from __future__ import annotations

import pytest

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.composition import CompositionType
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import PolicyStatus
from iac_agent.policies.composition import (
    API_LAMBDA_INVOKE_PERMISSION_REQUIRED,
    API_LAMBDA_NO_WILDCARD_PRINCIPAL,
    API_LAMBDA_ROUTE_EXPLICIT,
    REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE,
    SERVERLESS_DDB_WRITE_SCOPE_REQUIRED,
    SERVERLESS_NO_WILDCARD_IAM,
    SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED,
    evaluate_composition_policies,
)
from iac_agent.policies.platform import (
    DDB_DELETION_PROTECTION_RECOMMENDED,
    DDB_PITR_RECOMMENDED,
    LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    LAMBDA_TRACING_RECOMMENDED,
)
from iac_agent.policies.shared import TF_NO_DESTRUCTIVE_CHANGES
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import (
    LambdaResourceSpec,
    LambdaTracingMode,
)
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def _api_lambda_spec(**overrides) -> ApiLambdaSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
    }
    defaults.update(overrides)
    return ApiLambdaSpec(**defaults)


def _spec(**overrides) -> ServerlessWorkerSpec:
    defaults = {
        "name": "orders-worker",
        "queue": SQSResourceSpec(name="orders-queue"),
        "function": LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        "table": DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    }
    defaults.update(overrides)
    return ServerlessWorkerSpec(**defaults)


def _clean_plan_summary() -> PlanSummary:
    change = ResourceChange(
        address="module.queue.aws_sqs_queue.this",
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=(change.address,),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def _destructive_plan_summary() -> PlanSummary:
    change = ResourceChange(
        address="module.table.aws_dynamodb_table.this",
        actions=("delete",),
        action=PlanAction.DELETE,
        replacement=False,
        destructive=True,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=(),
        resources_to_change=(),
        resources_to_destroy=(change.address,),
        destructive_change_detected=True,
    )


def test_all_eight_policies_are_present_and_pass_for_a_clean_secure_composition():
    spec = _spec(
        function=LambdaResourceSpec(
            name="orders-processor", handler="app.handler", reserved_concurrency=5
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    findings_by_id = {f.policy_id: f for f in evaluation.findings}

    assert set(findings_by_id) == {
        SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED,
        SERVERLESS_DDB_WRITE_SCOPE_REQUIRED,
        SERVERLESS_NO_WILDCARD_IAM,
        LAMBDA_TRACING_RECOMMENDED,
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
        DDB_PITR_RECOMMENDED,
        DDB_DELETION_PROTECTION_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert all(f.status is PolicyStatus.PASS for f in findings_by_id.values())
    assert evaluation.overall_status is PolicyStatus.PASS


def test_lambda_tracing_pass_through_warns_inside_a_composition():
    spec = _spec(
        function=LambdaResourceSpec(
            name="orders-processor",
            handler="app.handler",
            reserved_concurrency=5,
            tracing_mode=LambdaTracingMode.PASS_THROUGH,
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == LAMBDA_TRACING_RECOMMENDED)
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_lambda_reserved_concurrency_omitted_warns_inside_a_composition():
    evaluation = evaluate_composition_policies(_spec(), _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED
    )
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_dynamodb_pitr_disabled_warns_inside_a_composition():
    spec = _spec(
        table=DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="pk", type="S"),
            point_in_time_recovery=False,
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == DDB_PITR_RECOMMENDED)
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_dynamodb_deletion_protection_disabled_warns_inside_a_composition():
    spec = _spec(
        table=DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="pk", type="S"),
            deletion_protection=False,
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == DDB_DELETION_PROTECTION_RECOMMENDED
    )
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_binding_policy_names_the_queue_and_function():
    evaluation = evaluate_composition_policies(_spec(), _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED
    )
    assert "orders-queue" in finding.message
    assert "orders-processor" in finding.message


def test_ddb_write_scope_policy_names_the_table():
    evaluation = evaluate_composition_policies(_spec(), _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == SERVERLESS_DDB_WRITE_SCOPE_REQUIRED
    )
    assert "orders-table" in finding.message


def test_destructive_plan_blocks_via_the_shared_platform_wide_policy():
    evaluation = evaluate_composition_policies(_spec(), _destructive_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_required_composition_policy_ids_registration_is_complete():
    required_ids = REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[
        CompositionType.SQS_LAMBDA_DYNAMODB
    ]
    evaluation = evaluate_composition_policies(_spec(), _clean_plan_summary())
    assert set(required_ids) == {f.policy_id for f in evaluation.findings}


# ---------------------------------------------------------------------------
# ApiLambdaSpec (Batch 20)
# ---------------------------------------------------------------------------


def test_all_six_api_lambda_policies_are_present_and_pass_for_a_secure_composition():
    spec = _api_lambda_spec(
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    findings_by_id = {f.policy_id: f for f in evaluation.findings}

    assert set(findings_by_id) == {
        API_LAMBDA_INVOKE_PERMISSION_REQUIRED,
        API_LAMBDA_NO_WILDCARD_PRINCIPAL,
        API_LAMBDA_ROUTE_EXPLICIT,
        LAMBDA_TRACING_RECOMMENDED,
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert all(f.status is PolicyStatus.PASS for f in findings_by_id.values())
    assert evaluation.overall_status is PolicyStatus.PASS


def test_api_lambda_tracing_pass_through_warns_inside_a_composition():
    spec = _api_lambda_spec(
        function=LambdaResourceSpec(
            name="orders-handler",
            handler="app.handler",
            reserved_concurrency=5,
            tracing_mode=LambdaTracingMode.PASS_THROUGH,
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == LAMBDA_TRACING_RECOMMENDED)
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_api_lambda_reserved_concurrency_omitted_warns_inside_a_composition():
    evaluation = evaluate_composition_policies(_api_lambda_spec(), _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED
    )
    assert finding.status is PolicyStatus.WARN
    assert evaluation.overall_status is PolicyStatus.WARN


def test_api_lambda_invoke_permission_policy_names_the_function():
    evaluation = evaluate_composition_policies(_api_lambda_spec(), _clean_plan_summary())
    finding = next(
        f for f in evaluation.findings if f.policy_id == API_LAMBDA_INVOKE_PERMISSION_REQUIRED
    )
    assert "orders-handler" in finding.message


def test_api_lambda_route_explicit_policy_names_the_route():
    evaluation = evaluate_composition_policies(_api_lambda_spec(), _clean_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == API_LAMBDA_ROUTE_EXPLICIT)
    assert "POST /orders" in finding.message


def test_api_lambda_destructive_plan_blocks_via_the_shared_platform_wide_policy():
    evaluation = evaluate_composition_policies(_api_lambda_spec(), _destructive_plan_summary())
    finding = next(f for f in evaluation.findings if f.policy_id == TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_required_api_lambda_composition_policy_ids_registration_is_complete():
    required_ids = REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[
        CompositionType.API_GATEWAY_LAMBDA
    ]
    spec = _api_lambda_spec(
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        )
    )
    evaluation = evaluate_composition_policies(spec, _clean_plan_summary())
    assert set(required_ids) == {f.policy_id for f in evaluation.findings}


def test_unsupported_composition_spec_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported composition spec type"):
        evaluate_composition_policies(object(), _clean_plan_summary())  # type: ignore[arg-type]

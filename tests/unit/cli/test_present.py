"""Batch 24, Task 6: presentation-safe stdout rendering (design spec
§7-§8). Fixtures are constructed directly — no graph, no Terraform, no
GitHub — and `ResolvedArchitecture` reuses the real `ArchitectureResolver`
so a real `ServerlessWorkerSpec` (with its resolver-owned defaults)
produces the component lines."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.cli.present import (
    _STANDALONE_RESOURCE_LABELS,
    _architecture_label,
    _component_lines,
    render_interpreter_error,
    render_submission,
    render_workflow,
)
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderTimeoutError
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_REQUEST_ID = "req-001"


def _worker_intent() -> ArchitectureIntent:
    return ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.PERSISTENCE, Capability.QUEUE_PROCESSING}),
    )


def _warn_gate() -> SecurityGateResult:
    finding = SecurityFinding(
        policy_id="LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED",
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource="fn",
        message="not set",
        source=FindingSource.PLATFORM_POLICY,
    )
    return SecurityGateResult(findings=(finding,))


def _plan_summary() -> PlanSummary:
    return PlanSummary(
        resource_changes=(),
        resources_to_add=tuple(f"addr-{i}" for i in range(10)),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def _awaiting_approval_worker_result() -> IntentSubmissionResult:
    intent = _worker_intent()
    resolution = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=WorkflowStage.APPROVAL,
        resource_name=resolution.request_spec.name,
        security_status="warn",
        plan_summary=_plan_summary(),
        approval_decision=None,
        pull_request=None,
        error=None,
        security_gate=_warn_gate(),
    )
    return IntentSubmissionResult(
        request_id=_REQUEST_ID, intent=intent, resolution=resolution, workflow_view=view
    )


def test_awaiting_approval_worker_report():
    output = render_submission(_awaiting_approval_worker_result())
    assert "architecture: serverless_worker" in output
    assert "security: warn" in output
    assert "approval: required" in output
    assert "capabilities: persistence, queue_processing" in output
    assert output.endswith("terraform apply: not executed")


def test_clarification_report():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    resolution = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    result = IntentSubmissionResult(
        request_id=_REQUEST_ID, intent=intent, resolution=resolution, workflow_view=None
    )
    output = render_submission(result)
    assert "field: workload_type" in output
    assert "terraform:" not in output
    assert "approval: not available" in output


def test_unsupported_report():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.PERSISTENCE}),
    )
    resolution = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    result = IntentSubmissionResult(
        request_id=_REQUEST_ID, intent=intent, resolution=resolution, workflow_view=None
    )
    output = render_submission(result)
    assert "reason:" in output


def test_blocked_report():
    intent = _worker_intent()
    resolution = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.BLOCKED,
        current_stage=WorkflowStage.SECURITY_GATE,
        resource_name=resolution.request_spec.name,
        security_status="block",
        plan_summary=_plan_summary(),
        approval_decision=None,
        pull_request=None,
        error=None,
        security_gate=None,
    )
    result = IntentSubmissionResult(
        request_id=_REQUEST_ID, intent=intent, resolution=resolution, workflow_view=view
    )
    output = render_submission(result)
    assert "outcome: blocked" in output
    assert "approval: not available" in output


def test_error_report():
    intent = _worker_intent()
    resolution = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.ERROR,
        current_stage=WorkflowStage.ERROR,
        resource_name=resolution.request_spec.name,
        security_status=None,
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=WorkflowError(
            stage=WorkflowStage.TERRAFORM, error_type="TerraformCommandError", message="boom"
        ),
        security_gate=None,
    )
    result = IntentSubmissionResult(
        request_id=_REQUEST_ID, intent=intent, resolution=resolution, workflow_view=view
    )
    output = render_submission(result)
    assert "error_type:" in output


def test_pr_created_report():
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.PR_CREATED,
        current_stage=WorkflowStage.COMPLETE,
        resource_name="orders-demo",
        security_status="warn",
        plan_summary=None,
        approval_decision=ApprovalDecision.APPROVE,
        pull_request=PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch="iac-agent/req-001",
            base_branch="main",
        ),
        error=None,
        security_gate=None,
    )
    output = render_workflow(view)
    assert "pull_request_url:" in output


def test_rejected_report():
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.REJECTED,
        current_stage=None,
        resource_name="orders-demo",
        security_status="warn",
        plan_summary=None,
        approval_decision=ApprovalDecision.REJECT,
        pull_request=None,
        error=None,
        security_gate=None,
    )
    output = render_workflow(view)
    assert "pull_request: -" in output


def test_interpreter_timeout_report():
    output = render_interpreter_error(
        request_id=_REQUEST_ID, exc=IntentProviderTimeoutError("timed out")
    )
    assert "error: intent_provider_timeout" in output
    assert "message: Intent provider timed out." in output


def test_workflow_error_message_still_printed_no_new_redaction_layer():
    """A `WorkflowError.message` is already a bounded, safe domain field
    (existing invariant) — this presenter must not add a second
    redaction layer beyond it."""
    view = WorkflowView(
        request_id=_REQUEST_ID,
        workflow_status=WorkflowStatus.ERROR,
        current_stage=WorkflowStage.ERROR,
        resource_name=None,
        security_status=None,
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=WorkflowError(
            stage=WorkflowStage.TERRAFORM,
            error_type="TerraformCommandError",
            message="failed near sk-live-secret in output",
        ),
        security_gate=None,
    )
    output = render_workflow(view)
    assert "sk-live-secret" in output


def test_normal_output_contains_no_sensitive_markers():
    output = render_submission(_awaiting_approval_worker_result())
    forbidden_markers = (
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "Authorization",
        "terraform_plan_json",
        "scanner_version",
    )
    for forbidden in forbidden_markers:
        assert forbidden not in output


def test_no_ansi_escapes():
    output = render_submission(_awaiting_approval_worker_result())
    assert "\x1b" not in output


# ---------------------------------------------------------------------------
# _architecture_label / _component_lines (Batch 26) — direct unit tests.
# No test previously exercised these two functions directly; this is
# exactly the gap that let _architecture_label's unconditional "s3"
# fallback go unnoticed for a type it had never seen before.
# ---------------------------------------------------------------------------


def _api_lambda_dynamodb_spec() -> ApiLambdaDynamoDbSpec:
    return ApiLambdaDynamoDbSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="id", type="S")
        ),
    )


def test_architecture_label_for_api_lambda_dynamodb_spec():
    assert _architecture_label(_api_lambda_dynamodb_spec()) == "API Gateway + Lambda + DynamoDB"


def test_architecture_label_for_api_lambda_dynamodb_spec_never_falls_through_to_s3():
    """The exact regression found during Batch 26 design: an
    unconditional `return "s3"` fallback would otherwise silently
    mislabel this composition."""
    assert _architecture_label(_api_lambda_dynamodb_spec()) != "s3"


def test_architecture_label_for_existing_compositions_and_s3_unchanged():
    worker_spec = ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )
    api_lambda_spec = ApiLambdaSpec(
        name="orders-api",
        api=ApiGatewayResourceSpec(name="orders-api-gw"),
        function=LambdaResourceSpec(name="orders-fn", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.GET, path="/orders"),
    )
    assert _architecture_label(worker_spec) == "serverless_worker"
    assert _architecture_label(api_lambda_spec) == "api_lambda"
    assert _architecture_label(S3ResourceSpec(name="orders-bucket")) == "s3"


def test_component_lines_for_api_lambda_dynamodb_spec_lists_all_three_resources():
    lines = _component_lines(_api_lambda_dynamodb_spec())
    assert lines == [
        "  api: orders-api",
        "  route: POST /orders",
        "  function: orders-handler",
        "  table: orders-table",
    ]


def test_every_resource_type_has_a_cli_architecture_label():
    for resource_type in ResourceType:
        assert resource_type in _STANDALONE_RESOURCE_LABELS


def test_architecture_label_for_ecr_is_ecr_not_s3():
    assert _architecture_label(EcrResourceSpec(name="orders")) == "ecr"


_STANDALONE_LABEL_CASES = (
    (SQSResourceSpec(name="order-events"), "sqs"),
    (
        DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
        "dynamodb",
    ),
    (LambdaResourceSpec(name="orders-processor", handler="app.handler"), "lambda"),
    (ApiGatewayResourceSpec(name="orders-api"), "api_gateway"),
    (S3ResourceSpec(name="orders-bucket"), "s3"),
)


def test_standalone_architecture_labels_match_resource_type_values():
    for spec, label in _STANDALONE_LABEL_CASES:
        assert _architecture_label(spec) == label


def test_ecr_component_lines_include_name_mutability_and_scan():
    lines = _component_lines(EcrResourceSpec(name="orders"))
    assert lines == [
        "  repository: orders",
        "  image_tag_mutability: IMMUTABLE",
        "  scan_on_push: true",
    ]

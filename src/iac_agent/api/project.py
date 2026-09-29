"""Project domain results into public HTTP DTOs. No FastAPI import."""

from __future__ import annotations

from iac_agent.api.schemas import (
    ComponentDTO,
    FindingDTO,
    IntentDTO,
    PlanDTO,
    PullRequestDTO,
    RequestListItem,
    RequestResponse,
    ResolutionDTO,
    WorkflowDTO,
    WorkflowErrorDTO,
)
from iac_agent.app.service import WorkflowView
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.resolver import (
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
)
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.resource import resource_type_of
from iac_agent.request import IacRequestSpec

_API_LAMBDA_DYNAMODB_LABEL = "API Gateway + Lambda + DynamoDB"
_STANDALONE_LABELS = {
    ResourceType.SQS: "sqs",
    ResourceType.S3: "s3",
    ResourceType.DYNAMODB: "dynamodb",
    ResourceType.LAMBDA: "lambda",
    ResourceType.API_GATEWAY: "api_gateway",
    ResourceType.ECR: "ecr",
}


def project_submission(result: IntentSubmissionResult) -> RequestResponse:
    match result.resolution:
        case ResolvedArchitecture() if result.workflow_view is not None:
            view = result.workflow_view
            return RequestResponse(
                request_id=result.request_id,
                outcome=view.workflow_status.value,
                approval_available=view.workflow_status is WorkflowStatus.AWAITING_APPROVAL,
                intent=_intent(result.intent),
                resolution=_resolved(result.resolution),
                workflow=_workflow(view),
            )
        case ClarificationRequired():
            request = result.resolution.request
            return RequestResponse(
                request_id=result.request_id,
                outcome="clarification_required",
                approval_available=False,
                intent=_intent(result.intent),
                resolution=ResolutionDTO(
                    outcome="clarification_required",
                    field=request.field,
                    reason=request.reason.value,
                    allowed_values=list(request.allowed_values),
                ),
                workflow=None,
            )
        case UnsupportedArchitecture():
            return RequestResponse(
                request_id=result.request_id,
                outcome="unsupported",
                approval_available=False,
                intent=_intent(result.intent),
                resolution=ResolutionDTO(
                    outcome="unsupported",
                    reason=result.resolution.reason.value,
                    detail=result.resolution.detail,
                ),
                workflow=None,
            )
        case _:
            raise TypeError(f"unsupported resolution {type(result.resolution).__name__}")


def project_list_item(view: WorkflowView, *, created_at: str) -> RequestListItem:
    """Public catalog row. Status fields come from the checkpoint view."""
    return RequestListItem(
        request_id=view.request_id,
        created_at=created_at,
        workflow_status=view.workflow_status.value,
        approval_available=view.workflow_status is WorkflowStatus.AWAITING_APPROVAL,
        security_status=view.security_status,
        name=view.resource_name,
    )


def project_view(view: WorkflowView) -> RequestResponse:
    """Project a checkpoint read. The view has no ArchitectureIntent."""
    return RequestResponse(
        request_id=view.request_id,
        outcome=view.workflow_status.value,
        approval_available=view.workflow_status is WorkflowStatus.AWAITING_APPROVAL,
        intent=None,
        resolution=ResolutionDTO(outcome="resolved", name=view.resource_name),
        workflow=_workflow(view),
    )


def _intent(intent: ArchitectureIntent) -> IntentDTO:
    return IntentDTO(
        workload_type=intent.workload_type.value,
        interaction_pattern=intent.interaction_pattern.value,
        capabilities=sorted(item.value for item in intent.capabilities),
    )


def _resolved(resolution: ResolvedArchitecture) -> ResolutionDTO:
    spec = resolution.request_spec
    return ResolutionDTO(
        outcome="resolved",
        matched_pattern=resolution.matched_pattern,
        architecture=_architecture(spec),
        name=spec.name,
        components=_components(spec),
    )


def _architecture(spec: IacRequestSpec) -> str:
    if isinstance(spec, ServerlessWorkerSpec):
        return "serverless_worker"
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        return _API_LAMBDA_DYNAMODB_LABEL
    if isinstance(spec, ApiLambdaSpec):
        return "api_lambda"
    return _STANDALONE_LABELS[resource_type_of(spec)]


def _components(spec: IacRequestSpec) -> list[ComponentDTO]:
    if isinstance(spec, ServerlessWorkerSpec):
        return [
            ComponentDTO(role="queue", name=spec.queue.name),
            ComponentDTO(role="function", name=spec.function.name),
            ComponentDTO(role="table", name=spec.table.name),
        ]
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        return [
            ComponentDTO(role="api", name=spec.api.name),
            ComponentDTO(role="route", name=f"{spec.route.method.value} {spec.route.path}"),
            ComponentDTO(role="function", name=spec.function.name),
            ComponentDTO(role="table", name=spec.table.name),
        ]
    if isinstance(spec, ApiLambdaSpec):
        return [
            ComponentDTO(role="api", name=spec.api.name),
            ComponentDTO(role="route", name=f"{spec.route.method.value} {spec.route.path}"),
            ComponentDTO(role="function", name=spec.function.name),
        ]
    if isinstance(spec, EcrResourceSpec):
        return [
            ComponentDTO(
                role="repository",
                name=spec.name,
                image_tag_mutability=spec.image_tag_mutability.value,
                scan_on_push=spec.scan_on_push,
            )
        ]
    return []


def _workflow(view: WorkflowView) -> WorkflowDTO:
    plan = view.plan_summary
    gate = view.security_gate
    error = view.error
    pull_request = view.pull_request
    return WorkflowDTO(
        workflow_status=view.workflow_status.value,
        current_stage=None if view.current_stage is None else view.current_stage.value,
        security_status=view.security_status,
        plan=None
        if plan is None
        else PlanDTO(
            add=plan.add_count,
            change=plan.change_count,
            destroy=plan.destroy_count,
            destructive_change_detected=plan.destructive_change_detected,
        ),
        findings=[
            FindingDTO(
                policy_id=finding.policy_id,
                status=finding.status.value,
                severity=finding.severity.value,
            )
            for finding in (() if gate is None else gate.findings)
        ],
        approval_decision=None
        if view.approval_decision is None
        else view.approval_decision.value,
        error=None
        if error is None
        else WorkflowErrorDTO(stage=error.stage.value, error_type=error.error_type),
        pull_request=None if pull_request is None else PullRequestDTO(url=pull_request.url),
    )

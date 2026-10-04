"""Pure, side-effect-free stdout rendering (design spec §7, §8).

Every function here is a pure function of already-safe, bounded domain
types — never `WorkflowState`, provider SDK objects, checkpoint
internals, or raw HTTP bodies. No I/O, no `sys.stdin`/`sys.stdout`
access; callers write the returned string themselves."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import (
    IntentProviderAuthenticationError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
)
from iac_agent.intent.resolver import (
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
)
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.resource import resource_type_of
from iac_agent.request import IacRequestSpec

_ERROR_CODES: dict[type[BaseException], tuple[str, str]] = {
    IntentProviderUnavailableError: (
        "intent_provider_unavailable",
        "Intent provider unavailable.",
    ),
    IntentProviderAuthenticationError: (
        "intent_provider_unavailable",
        "Intent provider unavailable.",
    ),
    IntentProviderTimeoutError: ("intent_provider_timeout", "Intent provider timed out."),
    IntentProviderRefusalError: (
        "intent_provider_refusal",
        "Intent provider declined to produce structured output.",
    ),
    IntentValidationError: ("intent_payload_malformed", "Intent payload was malformed."),
    IntentSchemaVersionUnsupportedError: (
        "intent_schema_unsupported",
        "Intent schema version is unsupported.",
    ),
}
_DEFAULT_ERROR_CODE = ("intent_interpretation_failed", "Intent interpretation failed.")

_TRAILER = "terraform apply: not executed"


def _intent_lines(intent: ArchitectureIntent) -> list[str]:
    capabilities = ", ".join(sorted(c.value for c in intent.capabilities))
    return [
        "intent:",
        f"  workload_type: {intent.workload_type.value}",
        f"  interaction_pattern: {intent.interaction_pattern.value}",
        f"  capabilities: {capabilities}",
        f"  logical_name_hint: {intent.logical_name_hint or '-'}",
    ]


#: Batch 26 closed decision: a human-readable label ("API Gateway +
#: Lambda + DynamoDB"), deliberately different in format from
#: `serverless_worker`/`api_lambda`'s existing snake_case labels below
#: — the human explicitly specified this exact string for this
#: composition, and the other two are left unchanged (existing
#: behavioral-compatibility invariant), so this is a one-off, not a new
#: general convention.
_API_LAMBDA_DYNAMODB_ARCHITECTURE_LABEL = "API Gateway + Lambda + DynamoDB"

_STANDALONE_RESOURCE_LABELS: dict[ResourceType, str] = {
    ResourceType.SQS: "sqs",
    ResourceType.S3: "s3",
    ResourceType.DYNAMODB: "dynamodb",
    ResourceType.LAMBDA: "lambda",
    ResourceType.API_GATEWAY: "api_gateway",
    ResourceType.ECR: "ecr",
}


def _architecture_label(spec: IacRequestSpec) -> str:
    if isinstance(spec, ServerlessWorkerSpec):
        return "serverless_worker"
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        # Checked before ApiLambdaSpec() only for readability — the two
        # are structurally distinct types (see
        # compositions/resource.py), so isinstance ordering doesn't
        # affect correctness here.
        return _API_LAMBDA_DYNAMODB_ARCHITECTURE_LABEL
    if isinstance(spec, ApiLambdaSpec):
        return "api_lambda"
    return _STANDALONE_RESOURCE_LABELS[resource_type_of(spec)]


def _component_lines(spec: IacRequestSpec) -> list[str]:
    if isinstance(spec, ServerlessWorkerSpec):
        return [
            f"  queue: {spec.queue.name}",
            f"  function: {spec.function.name}",
            f"  table: {spec.table.name}",
        ]
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        return [
            f"  api: {spec.api.name}",
            f"  route: {spec.route.method.value} {spec.route.path}",
            f"  function: {spec.function.name}",
            f"  table: {spec.table.name}",
        ]
    if isinstance(spec, ApiLambdaSpec):
        return [
            f"  api: {spec.api.name}",
            f"  route: {spec.route.method.value} {spec.route.path}",
            f"  function: {spec.function.name}",
        ]
    if isinstance(spec, EcrResourceSpec):
        return [
            f"  repository: {spec.name}",
            f"  image_tag_mutability: {spec.image_tag_mutability.value}",
            f"  scan_on_push: {str(spec.scan_on_push).lower()}",
        ]
    return []


def _findings_lines(security_gate) -> list[str]:
    if security_gate is None:
        return []
    non_pass = [f for f in security_gate.findings if f.status is not PolicyStatus.PASS]
    if not non_pass:
        return []
    non_pass = sorted(non_pass, key=lambda f: (f.policy_id, f.resource or ""))
    lines = ["findings:"]
    for finding in non_pass:
        resource = finding.resource or "-"
        lines.append(
            f"  - {finding.policy_id}  {finding.status.value}  "
            f"{finding.severity.value}  {resource}"
        )
    return lines


def render_submission(result: IntentSubmissionResult, *, include_resume_hint: bool = False) -> str:
    """Renders the initial `propose` report (design spec §7.1-§7.5).
    `include_resume_hint` is set only by the non-interactive-approval
    path (spec §6.6) — never by Task 6's own baseline fixtures."""
    lines = [f"request_id: {result.request_id}"]

    match result.resolution:
        case ResolvedArchitecture():
            view = result.workflow_view
            assert view is not None
            lines.append(f"outcome: {view.workflow_status.value}")
            lines.append("")
            lines.extend(_intent_lines(result.intent))
            lines.append("")
            lines.append("resolution: resolved")
            lines.append(f"  matched_pattern: {result.resolution.matched_pattern}")
            spec = result.resolution.request_spec
            lines.append(f"  architecture: {_architecture_label(spec)}")
            lines.append(f"  name: {spec.name}")
            lines.extend(_component_lines(spec))
            lines.append("")
            lines.append(f"workflow_status: {view.workflow_status.value}")
            if view.current_stage is not None:
                lines.append(f"current_stage: {view.current_stage.value}")

            if view.workflow_status is WorkflowStatus.ERROR:
                assert view.error is not None
                lines.append(f"error_stage: {view.error.stage.value}")
                lines.append(f"error_type: {view.error.error_type}")
                lines.append(f"error_message: {view.error.message}")
                lines.append("approval: not available")
            else:
                lines.append("terraform: validated")
                if view.plan_summary is not None:
                    plan = view.plan_summary
                    lines.append(
                        f"plan: +{plan.add_count} / ~{plan.change_count} / -{plan.destroy_count}"
                    )
                lines.append(f"security: {view.security_status}")
                lines.extend(_findings_lines(view.security_gate))
                if view.workflow_status is WorkflowStatus.AWAITING_APPROVAL:
                    lines.append("approval: required")
                    if include_resume_hint:
                        lines.append(
                            f"resume: iac-agent resume {result.request_id} --approve|--reject"
                        )
                else:
                    lines.append("approval: not available")
        case ClarificationRequired():
            lines.append("outcome: clarification_required")
            lines.append("")
            lines.extend(_intent_lines(result.intent))
            lines.append("")
            request = result.resolution.request
            lines.append("resolution: clarification_required")
            lines.append(f"  field: {request.field}")
            lines.append(f"  reason: {request.reason.value}")
            lines.append(f"  allowed_values: {', '.join(request.allowed_values)}")
            lines.append("")
            lines.append("approval: not available")
        case UnsupportedArchitecture():
            lines.append("outcome: unsupported")
            lines.append("")
            lines.extend(_intent_lines(result.intent))
            lines.append("")
            lines.append("resolution: unsupported")
            lines.append(f"  reason: {result.resolution.reason.value}")
            lines.append(f"  detail: {result.resolution.detail}")
            lines.append("")
            lines.append("approval: not available")

    lines.append(_TRAILER)
    return "\n".join(lines)


def render_workflow(view: WorkflowView) -> str:
    """Renders a `resume`/post-approval report (design spec §7.6-§7.7)
    and the `resume` command's defense-in-depth views for any other
    `WorkflowStatus`."""
    lines = [
        f"request_id: {view.request_id}",
        f"outcome: {view.workflow_status.value}",
        f"workflow_status: {view.workflow_status.value}",
    ]
    if view.current_stage is not None:
        lines.append(f"current_stage: {view.current_stage.value}")
    if view.approval_decision is not None:
        lines.append(f"approval_decision: {view.approval_decision.value}")

    if view.workflow_status is WorkflowStatus.PR_CREATED:
        pr = view.pull_request
        assert pr is not None
        lines.append(f"pull_request_number: {pr.number}")
        lines.append(f"pull_request_url: {pr.url}")
        lines.append(f"pull_request_branch: {pr.branch}")
        lines.append(f"pull_request_base: {pr.base_branch}")
    elif view.workflow_status is WorkflowStatus.REJECTED:
        lines.append("pull_request: -")
    elif view.workflow_status is WorkflowStatus.ERROR:
        assert view.error is not None
        lines.append(f"error_stage: {view.error.stage.value}")
        lines.append(f"error_type: {view.error.error_type}")
        lines.append(f"error_message: {view.error.message}")
    elif view.security_status is not None:
        lines.append(f"security: {view.security_status}")

    lines.append(_TRAILER)
    return "\n".join(lines)


def render_interpreter_error(*, request_id: str, exc: BaseException) -> str:
    """Maps by exception TYPE only (design spec §8) — never `str(exc)`,
    `__cause__`, or any provider SDK detail."""
    code, message = _ERROR_CODES.get(type(exc), _DEFAULT_ERROR_CODE)
    lines = [
        f"request_id: {request_id}",
        "outcome: error",
        f"error: {code}",
        f"message: {message}",
        "approval: not available",
        _TRAILER,
    ]
    return "\n".join(lines)


__all__ = [
    "render_submission",
    "render_workflow",
    "render_interpreter_error",
]

"""Batch 24, Task 6: presentation-safe stdout rendering (design spec
§7-§8). Fixtures are constructed directly — no graph, no Terraform, no
GitHub — and `ResolvedArchitecture` reuses the real `ArchitectureResolver`
so a real `ServerlessWorkerSpec` (with its resolver-owned defaults)
produces the component lines."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.cli.present import render_interpreter_error, render_submission, render_workflow
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
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

"""Allowlisted telemetry projection. Denied fields are absent from the models."""

from __future__ import annotations

from dataclasses import fields

import pytest

from iac_agent.app.service import WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.observability.models import GenerationTelemetry, WorkflowTelemetry
from iac_agent.observability.project import (
    project_generation,
    project_resolution,
    project_workflow,
)

_DENIED = {
    "natural_language_request",
    "assumptions",
    "unresolved_questions",
    "logical_name_hint",
    "confidence",
    "resource_name",
    "message",
    "resource",
    "address",
    "url",
    "branch",
    "generated_files",
    "traceback",
}


def test_telemetry_models_have_no_denylisted_fields():
    for model in (GenerationTelemetry, WorkflowTelemetry):
        names = {item.name for item in fields(model)}
        assert names.isdisjoint(_DENIED)


def test_project_generation_copies_tokens_only_when_present():
    full = project_generation(
        {
            "request_id": "req-001",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 12.5,
            "attempt_count": 1,
            "outcome_category": "ok",
            "input_tokens": 10,
            "output_tokens": 4,
            "natural_language_request": "build a bucket named secret-name",
            "raw_response": "should be dropped",
        }
    )
    assert full.input_tokens == 10
    assert full.output_tokens == 4
    assert "secret-name" not in repr(full)

    missing = project_generation(
        {
            "request_id": "req-001",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 1.0,
            "attempt_count": 2,
            "outcome_category": "timeout",
        }
    )
    assert missing.input_tokens is None
    assert missing.output_tokens is None


def test_project_resolution_keeps_enums_and_drops_names():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.CONTAINER_REGISTRY}),
        logical_name_hint="orders-registry",
        assumptions=("assume private",),
        unresolved_questions=("which region?",),
        user_provided_hints=(AwsServiceHint.ECR,),
    )
    resolution = ArchitectureResolver().resolve(intent=intent, request_id="req-001")
    event = project_resolution("req-001", intent, resolution)
    assert event.outcome == "resolved"
    assert event.resolved_type == "EcrResourceSpec"
    assert event.matched_pattern == "storage+container_registry"
    rendered = repr(event)
    assert "orders-registry" not in rendered
    assert "assume private" not in rendered
    assert "which region?" not in rendered


def test_project_workflow_keeps_counts_and_policy_ids_only():
    finding = SecurityFinding(
        policy_id="ECR_SCAN_ON_PUSH_RECOMMENDED",
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource="orders-registry",
        message="scan_on_push is false for orders-registry",
        source=FindingSource.PLATFORM_POLICY,
    )
    change = ResourceChange(
        address="module.ecr.aws_ecr_repository.this",
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    view = WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.BLOCKED,
        current_stage=WorkflowStage.SECURITY_GATE,
        resource_name="orders-registry",
        security_status="block",
        plan_summary=PlanSummary(
            resource_changes=(change,),
            resources_to_add=("module.ecr.aws_ecr_repository.this",),
            resources_to_change=(),
            resources_to_destroy=(),
            destructive_change_detected=False,
        ),
        approval_decision=None,
        pull_request=PullRequestResult(
            number=7,
            url="https://github.com/octo/example/pull/7",
            branch="iac-agent/req-001",
            base_branch="main",
        ),
        error=WorkflowError(
            stage=WorkflowStage.PLAN_ANALYSIS,
            error_type="TerraformCommandError",
            message="AWS_SECRET_ACCESS_KEY=supersecret",
        ),
        security_gate=SecurityGateResult(findings=(finding,)),
    )
    event = project_workflow(view, kind="terminal")
    rendered = repr(event)
    assert event.findings[0].policy_id == "ECR_SCAN_ON_PUSH_RECOMMENDED"
    assert event.findings[0].status == "warn"
    assert event.findings[0].severity == "medium"
    assert event.add_count == 1
    assert event.published is True
    assert "orders-registry" not in rendered
    assert "aws_ecr_repository" not in rendered
    assert "github.com" not in rendered
    assert "supersecret" not in rendered
    assert "AWS_SECRET_ACCESS_KEY" not in rendered


def test_project_workflow_rejects_an_unknown_kind():
    view = WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.ERROR,
        current_stage=WorkflowStage.ERROR,
        resource_name=None,
        security_status=None,
        plan_summary=None,
        approval_decision=ApprovalDecision.REJECT,
        pull_request=None,
        error=None,
    )
    with pytest.raises(ValueError):
        project_workflow(view, kind="get_state")

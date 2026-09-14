"""Deterministic LangGraph orchestration of the SQS pipeline.

`build_sqs_workflow` wires seven narrow nodes around the already-
proven deterministic components:

    render_terraform   -> TerraformCompositionRenderer
    terraform_execute   -> TerraformRunner (fmt, init, validate, plan)
    plan_analysis       -> TerraformRunner.show_json + analyze_plan
    platform_policy      -> evaluate_platform_policies
    checkov_scan         -> CheckovAdapter.scan
    security_gate        -> evaluate_security_gate
    approval_gate         -> a durable LangGraph `interrupt()` (Batch 13)

Each node consumes state, invokes exactly one existing capability, and
returns only its own state update. None of the underlying business
logic (contract validation, Terraform rendering/command semantics,
plan-action classification, platform policy rules, Checkov
normalization, security-gate precedence, or approval-decision parsing)
is reimplemented here — this module is orchestration only.

Any known boundary error (TerraformError, PlanAnalysisError,
CheckovError, SecurityGateError, InvalidApprovalDecisionError) is
caught at its node and translated into WorkflowStatus.ERROR + a safe
WorkflowError — never into BLOCKED, which means something different
(security evidence completed and explicitly rejected the change). If
any node sets ERROR, no later node runs; the graph routes straight to
END.

Batch 12 correction: `terraform_execute` no longer calls `show_json` or
writes a raw plan into state. `plan_analysis` now calls
`terraform_runner.show_json(...)` itself, holds the result in a local
variable only, and returns just the derived `PlanSummary`. This matters
once checkpointing is enabled (see `iac_agent.persistence`): anything
written into `WorkflowState` can be durably persisted to SQLite, so raw
Terraform plan JSON must never become a state value at all, not merely
be cleared later.

Batch 13 adds the human approval gate. `security_gate` no longer sets a
terminal PASS/WARN workflow status itself: a BLOCK result is terminal
(WorkflowStatus.BLOCKED, straight to END, no interrupt, no approval
path reachable); a PASS or WARN result instead sets
WorkflowStatus.AWAITING_APPROVAL and routes to `approval_gate`, which
calls LangGraph's `interrupt()` with a small, bounded, JSON-shaped
payload. Resuming with `Command(resume=...)` must supply exactly
`"approve"` or `"reject"` (see `iac_agent.domain.approval`); anything
else is a WorkflowStatus.ERROR, never a silent approval. Human approval
never rewrites `SecurityGateResult` — a WARN result is still inspectable
as WARN after the workflow reaches APPROVED. This durably pauses via
the same SQLite checkpointing introduced in Batch 12 — `interrupt()`
requires a checkpointer to be resumable at all.
"""

from __future__ import annotations

import os
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from iac_agent.domain.approval import (
    ApprovalDecision,
    InvalidApprovalDecisionError,
    parse_approval_decision,
)
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyStatus, SecurityGateResult
from iac_agent.domain.workflow import (
    WorkflowError,
    WorkflowStage,
    WorkflowStatus,
    validate_request_id,
)
from iac_agent.execution.plan_analyzer import PlanAnalysisError, analyze_plan
from iac_agent.execution.terraform_runner import TerraformError, TerraformRunner
from iac_agent.graph.state import WorkflowState
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter, CheckovError
from iac_agent.security.gate import SecurityGateError, evaluate_security_gate

#: Default location of the trusted SQS module, computed relative to
#: this installed package (src/iac_agent/graph/workflow.py -> repo
#: root -> terraform/modules/sqs). Overridable at construction time;
#: never inferred from the process working directory.
_DEFAULT_TRUSTED_MODULE_DIR = Path(__file__).resolve().parents[3] / "terraform" / "modules" / "sqs"

#: Placeholder-only credentials for the credential-free Terraform plan
#: design proven in Batches 3-9 — never real, never logged, never
#: stored in workflow state.
_PLAN_ENV_OVERRIDES = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}

_ERROR_MESSAGE_LIMIT = 500


def _approval_payload(state: WorkflowState) -> dict:
    """Build the bounded, JSON-shaped payload surfaced to a human
    reviewer via `interrupt()`.

    Deliberately built only from already-derived, already-normalized
    evidence (`PlanSummary`, `SecurityGateResult`) — never from raw
    Terraform/Checkov JSON, stdout/stderr, exception objects,
    environment values, or filesystem paths. Reused as-is on node
    re-execution after resume (LangGraph re-runs the node from the
    start): this function is pure and has no side effects.
    """
    gate_result: SecurityGateResult = state["security_gate"]
    plan_summary: PlanSummary = state["plan_summary"]

    return {
        "request_id": state["request_id"],
        "resource": state["resource_spec"].name,
        "security_status": gate_result.overall_status.value,
        "plan": {
            "add": plan_summary.add_count,
            "change": plan_summary.change_count,
            "destroy": plan_summary.destroy_count,
        },
        "findings": [
            {
                "policy_id": finding.policy_id,
                "status": finding.status.value,
                "severity": finding.severity.value,
                "resource": finding.resource,
            }
            for finding in gate_result.findings
        ],
    }


def _resolve_request_workspace(workspace_root: Path, request_id: str) -> Path:
    """Resolve `<workspace_root>/<request_id>`, rejecting anything that
    could escape `workspace_root` — using the same `request_id` safety
    rule shared with the checkpoint thread-ID mapping
    (`iac_agent.domain.workflow.validate_request_id`), not a second,
    independently-drifting rule set."""
    validate_request_id(request_id)
    return workspace_root / request_id


def _safe_error_message(exc: Exception) -> str:
    return str(exc)[:_ERROR_MESSAGE_LIMIT]


def _error_update(stage: WorkflowStage, exc: Exception) -> dict:
    return {
        "workflow_status": WorkflowStatus.ERROR,
        "current_stage": WorkflowStage.ERROR,
        "error": WorkflowError(
            stage=stage,
            error_type=type(exc).__name__,
            message=_safe_error_message(exc),
        ),
    }


def _route_unless_error(next_node: str):
    def _route(state: WorkflowState) -> str:
        if state.get("workflow_status") == WorkflowStatus.ERROR:
            return END
        return next_node

    return _route


def build_sqs_workflow(
    *,
    renderer: TerraformCompositionRenderer,
    terraform_runner: TerraformRunner,
    checkov_adapter: CheckovAdapter,
    workspace_root: Path,
    trusted_module_dir: Path = _DEFAULT_TRUSTED_MODULE_DIR,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build and compile the deterministic SQS workflow graph.

    All external boundaries are injected — no hidden global singletons,
    no real Terraform/Checkov requirement for callers who inject fakes.

    `checkpointer` is optional and backend-agnostic (any
    `BaseCheckpointSaver`, typically the SQLite-backed saver from
    `iac_agent.persistence.checkpoints`) — this module never
    constructs a SQLite connection itself. When `None` (the default),
    compilation is non-durable, preserving Batch 11's exact behavior.
    No `interrupt_before`/HITL configuration exists yet (that comes
    after persistence has a stable contract).
    """

    def render_terraform(state: WorkflowState) -> dict:
        try:
            workspace = _resolve_request_workspace(workspace_root, state["request_id"])
            module_source = os.path.relpath(trusted_module_dir, start=workspace)
            composition = renderer.render(state["resource_spec"], module_source=module_source)
            composition.write_to(workspace)
        except Exception as exc:  # noqa: BLE001 - sanitized below; KeyboardInterrupt/
            # SystemExit are BaseException subclasses and are never caught here.
            return _error_update(WorkflowStage.RENDER, exc)

        return {
            "workspace": workspace,
            "generated_files": dict(composition.files),
            "current_stage": WorkflowStage.TERRAFORM,
            "workflow_status": WorkflowStatus.RUNNING,
        }

    def terraform_execute(state: WorkflowState) -> dict:
        workspace = state["workspace"]
        try:
            terraform_runner.fmt(workspace)
            terraform_runner.init(workspace)
            terraform_runner.validate(workspace)
            terraform_runner.plan(workspace, env_overrides=_PLAN_ENV_OVERRIDES)
        except TerraformError as exc:
            return _error_update(WorkflowStage.TERRAFORM, exc)

        return {
            "current_stage": WorkflowStage.PLAN_ANALYSIS,
        }

    def plan_analysis(state: WorkflowState) -> dict:
        # `raw_plan` is a local variable ONLY — it is never assigned into
        # WorkflowState, so it can never be durably checkpointed. This is
        # the Batch 12 correction: previously `terraform_execute` wrote
        # the raw show-json result into state for this node to consume;
        # now this node fetches and consumes it in one step, and only
        # the derived PlanSummary ever becomes a state update.
        try:
            raw_plan = terraform_runner.show_json(state["workspace"])
            plan_summary: PlanSummary = analyze_plan(raw_plan)
        except (TerraformError, PlanAnalysisError) as exc:
            return _error_update(WorkflowStage.PLAN_ANALYSIS, exc)

        return {
            "plan_summary": plan_summary,
            "current_stage": WorkflowStage.PLATFORM_POLICY,
        }

    def platform_policy(state: WorkflowState) -> dict:
        try:
            platform_evaluation = evaluate_platform_policies(
                state["resource_spec"], state["plan_summary"]
            )
        except Exception as exc:  # noqa: BLE001 - a pure deterministic function
            # should never raise, but fail closed rather than crash the graph.
            return _error_update(WorkflowStage.PLATFORM_POLICY, exc)

        return {
            "platform_evaluation": platform_evaluation,
            "current_stage": WorkflowStage.CHECKOV,
        }

    def checkov_scan(state: WorkflowState) -> dict:
        try:
            checkov_result = checkov_adapter.scan(state["workspace"])
        except CheckovError as exc:
            return _error_update(WorkflowStage.CHECKOV, exc)

        return {
            "checkov_result": checkov_result,
            "current_stage": WorkflowStage.SECURITY_GATE,
        }

    def security_gate(state: WorkflowState) -> dict:
        try:
            gate_result = evaluate_security_gate(
                state["platform_evaluation"], state["checkov_result"]
            )
        except SecurityGateError as exc:
            return _error_update(WorkflowStage.SECURITY_GATE, exc)

        if gate_result.overall_status is PolicyStatus.BLOCK:
            # Terminal, by construction: no interrupt is ever reached for
            # a BLOCK result, so there is no resume path that could ever
            # turn this into an approval — the core Batch 13 security
            # rule (human approval must not override a deterministic
            # block) holds structurally, not merely by convention.
            return {
                "security_gate": gate_result,
                "workflow_status": WorkflowStatus.BLOCKED,
                "current_stage": WorkflowStage.COMPLETE,
            }

        return {
            "security_gate": gate_result,
            "workflow_status": WorkflowStatus.AWAITING_APPROVAL,
            "current_stage": WorkflowStage.APPROVAL,
        }

    def approval_gate(state: WorkflowState) -> dict:
        # Re-executed from the start on resume (LangGraph semantics for
        # `interrupt()`) — `_approval_payload` is pure, so recomputing it
        # is safe and always produces the same value.
        raw_decision = interrupt(_approval_payload(state))

        try:
            decision = parse_approval_decision(raw_decision)
        except InvalidApprovalDecisionError as exc:
            return _error_update(WorkflowStage.APPROVAL, exc)

        final_status = (
            WorkflowStatus.APPROVED
            if decision is ApprovalDecision.APPROVE
            else WorkflowStatus.REJECTED
        )
        return {
            "approval_decision": decision,
            "workflow_status": final_status,
            "current_stage": WorkflowStage.COMPLETE,
        }

    def _route_after_security_gate(state: WorkflowState) -> str:
        # BLOCK and ERROR both terminate at security_gate itself; only
        # AWAITING_APPROVAL ever proceeds to the interrupt.
        if state.get("workflow_status") == WorkflowStatus.AWAITING_APPROVAL:
            return "approval_gate"
        return END

    builder = StateGraph(WorkflowState)
    builder.add_node("render_terraform", render_terraform)
    builder.add_node("terraform_execute", terraform_execute)
    builder.add_node("plan_analysis", plan_analysis)
    builder.add_node("platform_policy", platform_policy)
    builder.add_node("checkov_scan", checkov_scan)
    builder.add_node("security_gate", security_gate)
    builder.add_node("approval_gate", approval_gate)

    builder.add_edge(START, "render_terraform")
    builder.add_conditional_edges("render_terraform", _route_unless_error("terraform_execute"))
    builder.add_conditional_edges("terraform_execute", _route_unless_error("plan_analysis"))
    builder.add_conditional_edges("plan_analysis", _route_unless_error("platform_policy"))
    builder.add_conditional_edges("platform_policy", _route_unless_error("checkov_scan"))
    builder.add_conditional_edges("checkov_scan", _route_unless_error("security_gate"))
    builder.add_conditional_edges("security_gate", _route_after_security_gate)
    builder.add_edge("approval_gate", END)

    return builder.compile(checkpointer=checkpointer)

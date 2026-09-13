"""Deterministic LangGraph orchestration of the SQS pipeline.

`build_sqs_workflow` wires exactly six narrow nodes around the already-
proven deterministic components:

    render_terraform   -> TerraformCompositionRenderer
    terraform_execute   -> TerraformRunner (fmt, init, validate, plan, show_json)
    plan_analysis       -> analyze_plan
    platform_policy      -> evaluate_platform_policies
    checkov_scan         -> CheckovAdapter.scan
    security_gate        -> evaluate_security_gate

Each node consumes state, invokes exactly one existing capability, and
returns only its own state update. None of the underlying business
logic (contract validation, Terraform rendering/command semantics,
plan-action classification, platform policy rules, Checkov
normalization, or security-gate precedence) is reimplemented here —
this module is orchestration only.

Any known boundary error (TerraformError, PlanAnalysisError,
CheckovError, SecurityGateError) is caught at its node and translated
into WorkflowStatus.ERROR + a safe WorkflowError — never into BLOCKED,
which means something different (security evidence completed and
explicitly rejected the change). If any node sets ERROR, no later
node runs; the graph routes straight to END.
"""

from __future__ import annotations

import os
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyStatus
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
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

_GATE_STATUS_TO_WORKFLOW_STATUS = {
    PolicyStatus.PASS: WorkflowStatus.PASS,
    PolicyStatus.WARN: WorkflowStatus.WARN,
    PolicyStatus.BLOCK: WorkflowStatus.BLOCKED,
}

_ERROR_MESSAGE_LIMIT = 500


def _resolve_request_workspace(workspace_root: Path, request_id: str) -> Path:
    """Resolve `<workspace_root>/<request_id>`, rejecting anything that
    could escape `workspace_root` — an absolute path, a path separator,
    or a parent-directory reference. `request_id` is never treated as a
    trusted filesystem path without this check."""
    if not request_id:
        raise ValueError("request_id must be a non-empty string")

    candidate = Path(request_id)
    if candidate.is_absolute():
        raise ValueError(f"request_id must not be an absolute path: {request_id!r}")
    if candidate.name != request_id or ".." in candidate.parts:
        raise ValueError(
            "request_id must be a simple path segment with no separators or "
            f"parent-directory references, got {request_id!r}"
        )
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
) -> CompiledStateGraph:
    """Build and compile the deterministic SQS workflow graph.

    All external boundaries are injected — no hidden global singletons,
    no real Terraform/Checkov requirement for callers who inject fakes.
    Compiled without a checkpointer (no durable persistence yet — that
    is Batch 12) and without any `interrupt_before`/HITL configuration
    (that comes after persistence has a stable contract).
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
            plan_json = terraform_runner.show_json(workspace)
        except TerraformError as exc:
            return _error_update(WorkflowStage.TERRAFORM, exc)

        return {
            "terraform_plan_json": plan_json,
            "current_stage": WorkflowStage.PLAN_ANALYSIS,
        }

    def plan_analysis(state: WorkflowState) -> dict:
        try:
            plan_summary: PlanSummary = analyze_plan(state["terraform_plan_json"])
        except PlanAnalysisError as exc:
            return _error_update(WorkflowStage.PLAN_ANALYSIS, exc)

        return {
            "plan_summary": plan_summary,
            # Raw plan JSON must not survive past this node.
            "terraform_plan_json": None,
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

        return {
            "security_gate": gate_result,
            "workflow_status": _GATE_STATUS_TO_WORKFLOW_STATUS[gate_result.overall_status],
            "current_stage": WorkflowStage.COMPLETE,
        }

    builder = StateGraph(WorkflowState)
    builder.add_node("render_terraform", render_terraform)
    builder.add_node("terraform_execute", terraform_execute)
    builder.add_node("plan_analysis", plan_analysis)
    builder.add_node("platform_policy", platform_policy)
    builder.add_node("checkov_scan", checkov_scan)
    builder.add_node("security_gate", security_gate)

    builder.add_edge(START, "render_terraform")
    builder.add_conditional_edges("render_terraform", _route_unless_error("terraform_execute"))
    builder.add_conditional_edges("terraform_execute", _route_unless_error("plan_analysis"))
    builder.add_conditional_edges("plan_analysis", _route_unless_error("platform_policy"))
    builder.add_conditional_edges("platform_policy", _route_unless_error("checkov_scan"))
    builder.add_conditional_edges("checkov_scan", _route_unless_error("security_gate"))
    builder.add_edge("security_gate", END)

    return builder.compile()

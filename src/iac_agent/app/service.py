"""The application service: submit / resume / get_state.

This is the boundary a future FastAPI/CLI layer would call — it never
constructs Terraform/LangGraph/GitHub objects itself (that is
`iac_agent.app.composition`'s job), and it never exposes raw
`WorkflowState` fields (workspace path, a GitHub token, raw
Terraform/Checkov JSON, exception objects, SQLite handles) to a caller.
Every result is a bounded `WorkflowView`.

Batch 19: `submit`'s type hint widens from `SQSResourceSpec` to
`IacRequestSpec` (`AWSResourceSpec | ServerlessWorkerSpec`) — a purely
free improvement. `open_application`'s compiled graph already builds
via the fully request-generalized `build_iac_workflow`
(`iac_agent.graph.workflow`), so it already accepts a
`ServerlessWorkerSpec` today; only this service's own type hint was
still narrower than what the graph beneath it actually supports.
`Phase1Application` is renamed to `IacApplication` to match (the class
no longer only runs "the Phase 1 SQS workflow"), with `Phase1Application`
kept as a zero-cost backward-compatible alias — the same pattern
`build_sqs_workflow` already established for `build_iac_workflow`.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from iac_agent.app.composition import Application
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.persistence.checkpoints import workflow_config
from iac_agent.request import IacRequestSpec


@dataclass(frozen=True)
class WorkflowView:
    """A bounded, application-facing view of one workflow run.

    Deliberately excludes: the workspace path, a GitHub token, raw
    Terraform plan JSON, raw Checkov data, exception objects, SQLite
    handles, or any other internal-transport detail — only the facts a
    caller (a future API/CLI layer, or a human operator) needs.
    """

    request_id: str
    workflow_status: WorkflowStatus
    current_stage: WorkflowStage | None
    resource_name: str | None
    security_status: str | None
    plan_summary: PlanSummary | None
    approval_decision: ApprovalDecision | None
    pull_request: PullRequestResult | None
    error: WorkflowError | None


def _to_view(request_id: str, values: dict) -> WorkflowView:
    resource_spec = values.get("resource_spec")
    security_gate = values.get("security_gate")
    return WorkflowView(
        request_id=request_id,
        workflow_status=values.get("workflow_status", WorkflowStatus.PENDING),
        current_stage=values.get("current_stage"),
        resource_name=resource_spec.name if resource_spec is not None else None,
        security_status=security_gate.overall_status.value if security_gate is not None else None,
        plan_summary=values.get("plan_summary"),
        approval_decision=values.get("approval_decision"),
        pull_request=values.get("pull_request"),
        error=values.get("error"),
    )


class IacApplication:
    """The controlled entry point for running the IaC request workflow
    — a single AWS resource, or (Batch 19) a serverless-worker
    composition.

    Holds only a compiled graph — no global/module-level state, so two
    independently constructed instances never share anything, even
    against the same durable database (thread isolation is the
    graph/checkpointer's own guarantee, already proven in Batch 12).
    """

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    @classmethod
    def from_application(cls, application: Application) -> IacApplication:
        return cls(application.graph)

    def submit(self, *, request_id: str, spec: IacRequestSpec) -> WorkflowView:
        """Invoke the workflow for a new request. For a secure valid
        request, the returned view's `workflow_status` is
        `AWAITING_APPROVAL`."""
        config = workflow_config(request_id)
        result = self._graph.invoke({"request_id": request_id, "resource_spec": spec}, config)
        return _to_view(request_id, result)

    def resume(self, request_id: str, decision: ApprovalDecision) -> WorkflowView:
        """Resume a durably-paused workflow with a human decision. Never
        bypasses the approval interrupt — this is the only way this
        service ever supplies a decision to the graph."""
        config = workflow_config(request_id)
        result = self._graph.invoke(Command(resume=decision.value), config)
        return _to_view(request_id, result)

    def get_state(self, request_id: str) -> WorkflowView:
        """Read the current durable state. Never executes a node, never
        resumes an interrupt, never mutates anything — `get_state` is a
        pure read against the checkpoint."""
        config = workflow_config(request_id)
        snapshot = self._graph.get_state(config)
        return _to_view(request_id, snapshot.values)


#: Zero-cost backward-compatible alias — mirrors `build_sqs_workflow`
#: remaining alongside `build_iac_workflow`. Every existing caller
#: spelling `Phase1Application` keeps working unchanged.
Phase1Application = IacApplication

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

import logging
from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from iac_agent.app.composition import Application
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import SecurityGateResult
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.noop import NoOpObservability
from iac_agent.observability.port import ObservabilityPort
from iac_agent.observability.project import project_workflow
from iac_agent.observability.sanitize import sanitize_telemetry
from iac_agent.persistence.checkpoints import workflow_config
from iac_agent.persistence.request_index import RequestIndex
from iac_agent.request import IacRequestSpec

_LOGGER = logging.getLogger("iac_agent.persistence")


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
    security_gate: SecurityGateResult | None = None


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
        security_gate=security_gate,
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

    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        observability: ObservabilityPort | None = None,
        request_index: RequestIndex | None = None,
    ) -> None:
        self._graph = graph
        self._observability = (
            observability
            if observability is not None
            else FailOpenObservability(NoOpObservability())
        )
        self._request_index = request_index

    @classmethod
    def from_application(cls, application: Application) -> IacApplication:
        return cls(application.graph)

    def submit(self, *, request_id: str, spec: IacRequestSpec) -> WorkflowView:
        """Invoke the workflow for a new request. For a secure valid
        request, the returned view's `workflow_status` is
        `AWAITING_APPROVAL`."""
        config = workflow_config(request_id)
        result = self._graph.invoke({"request_id": request_id, "resource_spec": spec}, config)
        view = self._emit(request_id, result, kind="submit")
        self._record_index(request_id)
        return view

    def resume(self, request_id: str, decision: ApprovalDecision) -> WorkflowView:
        """Resume a durably-paused workflow with a human decision. Never
        bypasses the approval interrupt — this is the only way this
        service ever supplies a decision to the graph."""
        config = workflow_config(request_id)
        result = self._graph.invoke(Command(resume=decision.value), config)
        return self._emit(request_id, result, kind="resume")

    def read(self, request_id: str) -> WorkflowView | None:
        """Return the checkpointed view, or None when no thread exists.

        LangGraph represents an unknown thread as a snapshot with
        `created_at is None` and empty values. This method does not turn
        that snapshot into `pending`. `get_state` remains the CLI read.
        """
        snapshot = self._graph.get_state(workflow_config(request_id))
        if snapshot.created_at is None:
            return None
        return _to_view(request_id, snapshot.values)

    def get_state(self, request_id: str) -> WorkflowView:
        """Read the current durable state. Never executes a node, never
        resumes an interrupt, never mutates anything — `get_state` is a
        pure read against the checkpoint."""
        config = workflow_config(request_id)
        snapshot = self._graph.get_state(config)
        return _to_view(request_id, snapshot.values)

    def _emit(self, request_id: str, values: dict, *, kind: str) -> WorkflowView:
        view = _to_view(request_id, values)
        self._observability.record_workflow(sanitize_telemetry(project_workflow(view, kind=kind)))
        if view.workflow_status is not WorkflowStatus.AWAITING_APPROVAL:
            self._observability.record_workflow(
                sanitize_telemetry(project_workflow(view, kind="terminal"))
            )
        self._observability.flush()
        return view

    def _record_index(self, request_id: str) -> None:
        """Best-effort catalog insert. A failure leaves a discovery gap only."""
        if self._request_index is None:
            return
        try:
            self._request_index.record(request_id)
        except Exception as exc:
            _LOGGER.warning(
                "request index insert failed",
                extra={"request_id": request_id, "error_type": type(exc).__name__},
            )


#: Zero-cost backward-compatible alias — mirrors `build_sqs_workflow`
#: remaining alongside `build_iac_workflow`. Every existing caller
#: spelling `Phase1Application` keeps working unchanged.
Phase1Application = IacApplication

"""The pre-workflow orchestrator (Batch 21, spec §9.1 — Option A).

`IntentResolutionService` sits *in front of* `IacApplication` — it
never modifies `build_iac_workflow`, `WorkflowState`, or
`WorkflowStatus`. A `ResolvedArchitecture` becomes simply another value
handed to the exact same `IacApplication.submit()` every existing
caller already uses; `ClarificationRequired`, `UnsupportedArchitecture`,
and any `IntentInterpreterError` never reach `IacApplication` at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from iac_agent.app.service import IacApplication, WorkflowView
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import IntentInterpreterError, IntentInterpreterPort
from iac_agent.intent.resolver import ArchitectureResolver, ResolutionResult, ResolvedArchitecture
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.noop import NoOpObservability
from iac_agent.observability.port import ObservabilityPort
from iac_agent.observability.project import project_generation, project_resolution
from iac_agent.observability.sanitize import sanitize_telemetry


@dataclass(frozen=True)
class IntentSubmissionResult:
    """`workflow_view` is non-`None` only when `resolution` is a
    `ResolvedArchitecture` — every other outcome never reaches
    `IacApplication` at all. `intent` is always set: interpreter
    failures never produce this object at all (they propagate
    uncaught), so by the time this dataclass exists, `interpret()` has
    already succeeded."""

    request_id: str
    intent: ArchitectureIntent
    resolution: ResolutionResult
    workflow_view: WorkflowView | None

    @property
    def approval_available(self) -> bool:
        return (
            self.workflow_view is not None
            and self.workflow_view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
        )


class IntentResolutionService:
    """Orchestrates `IntentInterpreterPort.interpret()` ->
    `ArchitectureResolver.resolve()` -> (only when resolved)
    `IacApplication.submit()`.

    Any `IntentInterpreterError` subtype raised by `interpret()`
    propagates uncaught — a system failure, never converted into a
    `ResolutionResult` (spec §1.5, §10).
    """

    def __init__(
        self,
        *,
        interpreter: IntentInterpreterPort,
        resolver: ArchitectureResolver,
        application: IacApplication,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self._interpreter = interpreter
        self._resolver = resolver
        self._application = application
        self._observability = (
            observability
            if observability is not None
            else FailOpenObservability(NoOpObservability())
        )

    def submit(self, *, request_id: str, natural_language_request: str) -> IntentSubmissionResult:
        try:
            intent = self._interpreter.interpret(
                natural_language_request=natural_language_request, request_id=request_id
            )
        except IntentInterpreterError:
            self._emit_generation(request_id)
            raise
        self._emit_generation(request_id)
        result = self._resolver.resolve(intent=intent, request_id=request_id)
        self._observability.record_resolution(
            sanitize_telemetry(project_resolution(request_id, intent, result))
        )
        self._observability.flush()

        match result:
            case ResolvedArchitecture():
                view = self._application.submit(request_id=request_id, spec=result.request_spec)
                return IntentSubmissionResult(
                    request_id=request_id, intent=intent, resolution=result, workflow_view=view
                )
            case _:
                return IntentSubmissionResult(
                    request_id=request_id, intent=intent, resolution=result, workflow_view=None
                )

    def _emit_generation(self, request_id: str) -> None:
        metadata = getattr(self._interpreter, "last_call_metadata", None)
        if metadata is None:
            return
        self._observability.record_generation(sanitize_telemetry(project_generation(metadata)))

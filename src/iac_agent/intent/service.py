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
from iac_agent.intent.port import IntentInterpreterPort
from iac_agent.intent.resolver import ArchitectureResolver, ResolutionResult, ResolvedArchitecture


@dataclass(frozen=True)
class IntentSubmissionResult:
    """`workflow_view` is non-`None` only when `resolution` is a
    `ResolvedArchitecture` — every other outcome never reaches
    `IacApplication` at all."""

    resolution: ResolutionResult
    workflow_view: WorkflowView | None


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
    ) -> None:
        self._interpreter = interpreter
        self._resolver = resolver
        self._application = application

    def submit(self, *, request_id: str, natural_language_request: str) -> IntentSubmissionResult:
        intent = self._interpreter.interpret(
            natural_language_request=natural_language_request, request_id=request_id
        )
        result = self._resolver.resolve(intent=intent, request_id=request_id)

        match result:
            case ResolvedArchitecture():
                view = self._application.submit(request_id=request_id, spec=result.request_spec)
                return IntentSubmissionResult(resolution=result, workflow_view=view)
            case _:
                return IntentSubmissionResult(resolution=result, workflow_view=None)

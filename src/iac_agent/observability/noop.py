"""Observability that records nothing."""

from __future__ import annotations

from iac_agent.observability.models import (
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)


class NoOpObservability:
    def record_generation(self, event: GenerationTelemetry) -> None:
        return None

    def record_resolution(self, event: ResolutionTelemetry) -> None:
        return None

    def record_workflow(self, event: WorkflowTelemetry) -> None:
        return None

    def flush(self) -> None:
        return None

"""The observability notification port.

Success returns None. Unlike IntentInterpreterPort, implementations
must not be the thing that fails a workflow. FailOpenObservability is
the isolation boundary.
"""

from __future__ import annotations

from typing import Protocol

from iac_agent.observability.models import (
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)


class ObservabilityPort(Protocol):
    def record_generation(self, event: GenerationTelemetry) -> None: ...

    def record_resolution(self, event: ResolutionTelemetry) -> None: ...

    def record_workflow(self, event: WorkflowTelemetry) -> None: ...

    def flush(self) -> None: ...

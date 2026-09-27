"""Isolate telemetry failures from the workflow that already finished."""

from __future__ import annotations

import logging

from iac_agent.observability.port import ObservabilityPort

_LOGGER = logging.getLogger("iac_agent.observability")


class FailOpenObservability:
    def __init__(self, inner: ObservabilityPort) -> None:
        self._inner = inner

    def record_generation(self, event) -> None:
        self._call(self._inner.record_generation, event)

    def record_resolution(self, event) -> None:
        self._call(self._inner.record_resolution, event)

    def record_workflow(self, event) -> None:
        self._call(self._inner.record_workflow, event)

    def flush(self) -> None:
        self._call(self._inner.flush, None)

    def _call(self, method, event) -> None:
        try:
            if event is None:
                method()
            else:
                method(event)
        except Exception as exc:
            _LOGGER.warning(
                "observability %s raised",
                method.__name__,
                extra={
                    "request_id": getattr(event, "request_id", None),
                    "error_type": type(exc).__name__,
                },
            )

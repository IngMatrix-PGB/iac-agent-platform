"""NoOp and fail-open observability port."""

from __future__ import annotations

import logging

from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.models import (
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)
from iac_agent.observability.noop import NoOpObservability


class _Boom:
    def record_generation(self, event) -> None:
        raise RuntimeError("langfuse down")

    def record_resolution(self, event) -> None:
        raise TimeoutError("telemetry timeout")

    def record_workflow(self, event) -> None:
        raise ValueError("cannot serialize")

    def flush(self) -> None:
        raise OSError("flush failed")


def _generation() -> GenerationTelemetry:
    return GenerationTelemetry(
        request_id="req-001",
        provider="openai",
        model="gpt-test",
        prompt_version="4",
        latency_ms=1.0,
        attempt_count=1,
        outcome_category="ok",
    )


def _resolution() -> ResolutionTelemetry:
    return ResolutionTelemetry(
        request_id="req-001",
        outcome="resolved",
        workload_type="storage",
        interaction_pattern="unspecified",
        capabilities=("container_registry",),
        user_provided_hints=(),
    )


def _workflow() -> WorkflowTelemetry:
    return WorkflowTelemetry(
        request_id="req-001",
        kind="terminal",
        workflow_status="error",
        current_stage=None,
        security_status=None,
        add_count=None,
        change_count=None,
        destroy_count=None,
        destructive_change_detected=None,
        findings=(),
        approval_decision=None,
        error_stage=None,
        error_type=None,
        published=False,
    )


def test_noop_methods_return_none():
    port = NoOpObservability()
    assert port.record_generation(_generation()) is None
    assert port.record_resolution(_resolution()) is None
    assert port.record_workflow(_workflow()) is None
    assert port.flush() is None


def test_failopen_swallows_record_and_flush_failures(caplog):
    port = FailOpenObservability(_Boom())
    with caplog.at_level(logging.WARNING):
        port.record_generation(_generation())
        port.record_resolution(_resolution())
        port.record_workflow(_workflow())
        port.flush()
    error_types = [record.error_type for record in caplog.records]
    assert error_types == ["RuntimeError", "TimeoutError", "ValueError", "OSError"]
    text = caplog.text
    assert "langfuse down" not in text
    assert "telemetry timeout" not in text
    assert "cannot serialize" not in text
    assert "flush failed" not in text
    assert any(getattr(record, "request_id", None) == "req-001" for record in caplog.records)
    flush_records = [record for record in caplog.records if record.error_type == "OSError"]
    assert flush_records[0].request_id is None

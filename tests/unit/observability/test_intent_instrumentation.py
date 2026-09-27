"""IntentResolutionService emits allowlisted telemetry and does not swallow intent errors."""

from __future__ import annotations

import pytest

from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderTimeoutError
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.observability.failopen import FailOpenObservability


class RecordingObservability:
    def __init__(self, *, fail_resolution: bool = False) -> None:
        self.generations = []
        self.resolutions = []
        self.workflows = []
        self.flushes = 0
        self._fail_resolution = fail_resolution

    def record_generation(self, event) -> None:
        self.generations.append(event)

    def record_resolution(self, event) -> None:
        if self._fail_resolution:
            raise RuntimeError("resolution telemetry failed")
        self.resolutions.append(event)

    def record_workflow(self, event) -> None:
        self.workflows.append(event)

    def flush(self) -> None:
        self.flushes += 1


class _NeverSubmit:
    def submit(self, **kwargs):
        raise AssertionError("submit must not be called")


class _Interpreter:
    def __init__(self, *, intent=None, raises=None, metadata=None, expose_metadata=True):
        self._intent = intent
        self._raises = raises
        self._metadata = metadata
        self._expose_metadata = expose_metadata
        self.prompts: list[str] = []

    def interpret(self, *, natural_language_request: str, request_id: str):
        self.prompts.append(natural_language_request)
        if self._expose_metadata:
            self.last_call_metadata = self._metadata
        if self._raises is not None:
            raise self._raises
        return self._intent


def _ecr_intent() -> ArchitectureIntent:
    return ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.CONTAINER_REGISTRY}),
        logical_name_hint="orders-registry",
    )


def _metadata(*, tokens: bool) -> dict:
    payload = {
        "request_id": "req-001",
        "provider": "openai",
        "model": "gpt-test",
        "prompt_version": "4",
        "latency_ms": 3.0,
        "attempt_count": 1,
        "outcome_category": "schema_valid",
    }
    if tokens:
        payload["input_tokens"] = 11
        payload["output_tokens"] = 2
    return payload


class _ViewlessApplication:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def submit(self, *, request_id, spec):
        self.calls.append(request_id)
        return None


def _service(interpreter, recorder, application=None):
    return IntentResolutionService(
        interpreter=interpreter,
        resolver=ArchitectureResolver(),
        application=_ViewlessApplication() if application is None else application,
        observability=recorder,
    )


def test_resolved_intent_records_generation_and_resolution_without_the_prompt():
    recorder = RecordingObservability()
    interpreter = _Interpreter(intent=_ecr_intent(), metadata=_metadata(tokens=True))
    result = _service(interpreter, recorder).submit(
        request_id="req-001",
        natural_language_request="build a registry named orders-registry",
    )
    assert result.resolution.outcome == "resolved"
    assert len(recorder.generations) == 1
    assert recorder.generations[0].input_tokens == 11
    assert recorder.resolutions[0].resolved_type == "EcrResourceSpec"
    rendered = repr(recorder.generations) + repr(recorder.resolutions)
    assert "build a registry named orders-registry" not in rendered
    assert "orders-registry" not in rendered
    assert recorder.flushes == 1


def test_missing_token_usage_is_valid():
    recorder = RecordingObservability()
    interpreter = _Interpreter(intent=_ecr_intent(), metadata=_metadata(tokens=False))
    _service(interpreter, recorder).submit(
        request_id="req-001", natural_language_request="build a registry"
    )
    assert recorder.generations[0].input_tokens is None
    assert recorder.generations[0].output_tokens is None


def test_interpreter_without_metadata_still_records_resolution():
    recorder = RecordingObservability()
    interpreter = _Interpreter(intent=_ecr_intent(), expose_metadata=False)
    _service(interpreter, recorder).submit(
        request_id="req-001", natural_language_request="build a registry"
    )
    assert recorder.generations == []
    assert recorder.resolutions[0].outcome == "resolved"


def test_clarification_does_not_submit_or_emit_workflow():
    recorder = RecordingObservability()
    intent = ArchitectureIntent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    result = _service(
        _Interpreter(intent=intent, metadata=None), recorder, application=_NeverSubmit()
    ).submit(
        request_id="req-002", natural_language_request="do something"
    )
    assert result.workflow_view is None
    assert result.resolution.outcome == "clarification_required"
    assert recorder.resolutions[0].clarification_reason == "workload_type_required"
    assert recorder.workflows == []


def test_unsupported_does_not_submit():
    recorder = RecordingObservability()
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.PERSISTENCE}),
    )
    result = _service(
        _Interpreter(intent=intent, metadata=None), recorder, application=_NeverSubmit()
    ).submit(
        request_id="req-003", natural_language_request="build an aurora db"
    )
    assert result.workflow_view is None
    assert result.resolution.outcome == "unsupported"
    assert recorder.resolutions[0].unsupported_reason is not None


def test_interpreter_error_is_reraised_after_generation_metadata():
    recorder = RecordingObservability()
    interpreter = _Interpreter(
        raises=IntentProviderTimeoutError("timed out"),
        metadata={
            "request_id": "req-004",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 1.0,
            "attempt_count": 2,
            "outcome_category": "timeout",
        },
    )
    with pytest.raises(IntentProviderTimeoutError):
        _service(interpreter, recorder).submit(
            request_id="req-004", natural_language_request="build me an api"
        )
    assert len(recorder.generations) == 1
    assert recorder.generations[0].outcome_category == "timeout"
    assert recorder.resolutions == []
    assert "timed out" not in repr(recorder.generations)


def test_resolution_telemetry_failure_does_not_change_the_submission():
    interpreter = _Interpreter(intent=_ecr_intent(), metadata=_metadata(tokens=True))
    failing = FailOpenObservability(RecordingObservability(fail_resolution=True))
    healthy = RecordingObservability()
    failed = _service(interpreter, failing).submit(
        request_id="req-001", natural_language_request="build a registry"
    )
    succeeded = _service(
        _Interpreter(intent=_ecr_intent(), metadata=_metadata(tokens=True)), healthy
    ).submit(request_id="req-001", natural_language_request="build a registry")
    assert failed.resolution.outcome == succeeded.resolution.outcome == "resolved"
    assert type(failed.resolution.request_spec) is type(succeeded.resolution.request_spec)
    assert failed.workflow_view is None
    assert succeeded.workflow_view is None

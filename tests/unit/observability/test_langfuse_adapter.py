"""Langfuse adapter against an injected client. No network and no SDK import."""

from __future__ import annotations

import hashlib

import pytest

from iac_agent.app.service import IacApplication
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.observability.adapters.langfuse import LangfuseObservability, SdkTraceClient
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.models import (
    FindingTelemetry,
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult

_DENIED_KEYS = {
    "natural_language_request",
    "assumptions",
    "unresolved_questions",
    "logical_name_hint",
    "prompt",
    "completion",
    "input",
    "output",
    "resource_name",
    "message",
    "resource",
    "address",
    "url",
    "branch",
    "generated_files",
    "traceback",
    "stderr",
    "stdout",
}

_DENIED_TEXT = (
    "build a registry named orders-registry",
    "orders-registry",
    "module.queue.aws_sqs_queue.this",
    "arn:aws:ecr:us-east-1:123456789012:repository/orders",
    "123456789012",
    "Checkov CKV_AWS_27 failed.",
    "benign failure",
    "https://github.com/octo/example/pull/7",
    "AWS_SECRET_ACCESS_KEY",
    "sk-live-secret",
    "# fake",
)


def _trace_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


class FakeClient:
    def __init__(self) -> None:
        self.seeds: list[str] = []
        self.observations: list[dict] = []
        self.flushes = 0

    def create_trace_id(self, *, seed: str) -> str:
        self.seeds.append(seed)
        return _trace_id(seed)

    def emit(self, **payload) -> None:
        self.observations.append(payload)

    def flush(self) -> None:
        self.flushes += 1


class _RaisingClient(FakeClient):
    def __init__(self, *, on: str) -> None:
        super().__init__()
        self._on = on

    def emit(self, **payload) -> None:
        if self._on == "emit":
            raise RuntimeError("sdk down")
        super().emit(**payload)

    def flush(self) -> None:
        if self._on == "flush":
            raise OSError("flush failed")
        super().flush()


def _generation(*, tokens: bool) -> GenerationTelemetry:
    return GenerationTelemetry(
        request_id="req-same",
        provider="openai",
        model="gpt-test",
        prompt_version="4",
        latency_ms=3.5,
        attempt_count=1,
        outcome_category="schema_valid",
        input_tokens=11 if tokens else None,
        output_tokens=2 if tokens else None,
    )


def _resolution() -> ResolutionTelemetry:
    return ResolutionTelemetry(
        request_id="req-same",
        outcome="resolved",
        workload_type="storage",
        interaction_pattern="unspecified",
        capabilities=("container_registry",),
        user_provided_hints=("ecr",),
        matched_pattern="storage+container_registry",
        resolved_type="EcrResourceSpec",
    )


def _workflow(kind: str) -> WorkflowTelemetry:
    return WorkflowTelemetry(
        request_id="req-same",
        kind=kind,  # type: ignore[arg-type]
        workflow_status="awaiting_approval" if kind == "submit" else "pr_created",
        current_stage="approval",
        security_status="pass",
        add_count=1,
        change_count=0,
        destroy_count=0,
        destructive_change_detected=False,
        findings=(FindingTelemetry(policy_id="CKV_AWS_27", status="pass", severity="high"),),
        approval_decision="approve" if kind != "submit" else None,
        error_stage=None,
        error_type=None,
        published=kind == "terminal",
    )


def _assert_clean(payload: dict) -> None:
    rendered = repr(payload)
    for key in _DENIED_KEYS:
        assert key not in payload
        assert key not in payload.get("metadata", {})
    for needle in _DENIED_TEXT:
        assert needle not in rendered


def test_same_request_id_keeps_one_trace_id_across_fresh_clients():
    first = FakeClient()
    second = FakeClient()
    LangfuseObservability(first).record_workflow(_workflow("submit"))
    LangfuseObservability(second).record_workflow(_workflow("resume"))
    assert first.seeds == ["req-same"]
    assert second.seeds == ["req-same"]
    assert first.observations[0]["trace_id"] == second.observations[0]["trace_id"]
    other = FakeClient()
    event = _workflow("terminal")
    LangfuseObservability(other).record_workflow(
        WorkflowTelemetry(
            request_id="req-other",
            kind="terminal",
            workflow_status=event.workflow_status,
            current_stage=event.current_stage,
            security_status=event.security_status,
            add_count=event.add_count,
            change_count=event.change_count,
            destroy_count=event.destroy_count,
            destructive_change_detected=event.destructive_change_detected,
            findings=event.findings,
            approval_decision=event.approval_decision,
            error_stage=event.error_stage,
            error_type=event.error_type,
            published=event.published,
        )
    )
    assert other.observations[0]["trace_id"] != first.observations[0]["trace_id"]


def test_generation_maps_metadata_and_tokens_only_when_present():
    client = FakeClient()
    LangfuseObservability(client).record_generation(_generation(tokens=True))
    payload = client.observations[0]
    assert payload["name"] == "intent.interpret"
    assert payload["as_type"] == "generation"
    assert payload["model"] == "gpt-test"
    assert payload["usage"] == {"input": 11, "output": 2}
    assert payload["metadata"]["prompt_version"] == "4"
    assert "input_tokens" not in payload["metadata"]
    _assert_clean(payload)

    bare = FakeClient()
    LangfuseObservability(bare).record_generation(_generation(tokens=False))
    assert "usage" not in bare.observations[0]
    assert bare.observations[0]["metadata"]["outcome_category"] == "schema_valid"


def test_resolution_and_workflow_events_use_allowlisted_fields():
    client = FakeClient()
    adapter = LangfuseObservability(client)
    adapter.record_resolution(_resolution())
    adapter.record_workflow(_workflow("submit"))
    adapter.record_workflow(_workflow("resume"))
    adapter.record_workflow(_workflow("terminal"))
    adapter.flush()
    names = [item["name"] for item in client.observations]
    assert names == [
        "intent.resolve",
        "workflow.submit",
        "workflow.resume",
        "workflow.terminal",
    ]
    assert all(item["as_type"] == "event" for item in client.observations)
    assert client.flushes == 1
    resolve = client.observations[0]["metadata"]
    assert resolve["resolved_type"] == "EcrResourceSpec"
    assert resolve["matched_pattern"] == "storage+container_registry"
    finding = client.observations[1]["metadata"]["findings"][0]
    assert finding == {"policy_id": "CKV_AWS_27", "status": "pass", "severity": "high"}
    for payload in client.observations:
        _assert_clean(payload)


def test_sdk_wrapper_does_not_send_prompt_or_completion():
    class _Observation:
        def __init__(self) -> None:
            self.updates: list[dict] = []

        def update(self, **kwargs) -> None:
            self.updates.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    class _Sdk:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.observation = _Observation()

        def create_trace_id(self, *, seed: str) -> str:
            return _trace_id(seed)

        def start_as_current_observation(self, **kwargs):
            self.calls.append(kwargs)
            return self.observation

        def flush(self) -> None:
            return None

    sdk = _Sdk()
    client = SdkTraceClient(sdk)
    LangfuseObservability(client).record_generation(_generation(tokens=True))
    call = sdk.calls[0]
    assert call["as_type"] == "generation"
    assert call["name"] == "intent.interpret"
    assert call["trace_context"]["trace_id"] == _trace_id("req-same")
    assert "input" not in call
    assert "output" not in call
    assert "prompt" not in call
    assert sdk.observation.updates == [{"usage_details": {"input": 11, "output": 2}}]


class _Interpreter:
    def __init__(self) -> None:
        self.last_call_metadata = {
            "request_id": "req-001",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 1.0,
            "attempt_count": 1,
            "outcome_category": "schema_valid",
        }

    def interpret(self, *, natural_language_request: str, request_id: str):
        return ArchitectureIntent(
            workload_type=WorkloadType.STORAGE,
            interaction_pattern=InteractionPattern.UNSPECIFIED,
            capabilities=frozenset({Capability.CONTAINER_REGISTRY}),
            logical_name_hint="orders-registry",
        )


def test_emit_failure_does_not_change_the_resolved_submission():
    port = FailOpenObservability(LangfuseObservability(_RaisingClient(on="emit")))
    result = IntentResolutionService(
        interpreter=_Interpreter(),
        resolver=ArchitectureResolver(),
        application=type("App", (), {"submit": lambda *a, **k: None})(),
        observability=port,
    ).submit(
        request_id="req-001",
        natural_language_request="build a registry named orders-registry",
    )
    assert result.resolution.outcome == "resolved"
    assert type(result.resolution.request_spec).__name__ == "EcrResourceSpec"


def _ok(command: str) -> CommandResult:
    return CommandResult(
        command=("terraform", command), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class _Runner:
    def fmt(self, workspace, **kwargs):
        return _ok("fmt")

    def init(self, workspace, **kwargs):
        return _ok("init")

    def validate(self, workspace, **kwargs):
        return _ok("validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        return _ok("plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return {
            "terraform_version": "1.16.1",
            "resource_changes": [
                {
                    "address": "module.queue.aws_sqs_queue.this",
                    "change": {"actions": ["create"], "before": None, "after": {}},
                }
            ],
        }


class _Renderer:
    def render(self, spec, *, module_source):
        return GeneratedTerraformComposition(files={"main.tf": "# fake\n"})


class _Checkov:
    def scan(self, workspace, *, profile=None):
        return CheckovScanResult(
            findings=(),
            passed_checks=1,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="3.3.13",
        )


class _Source:
    def publish_change(self, **kwargs):
        raise AssertionError("publish must not run")


def test_flush_failure_does_not_change_awaiting_approval(tmp_path):
    graph = build_sqs_workflow(
        renderer=_Renderer(),
        terraform_runner=_Runner(),
        checkov_adapter=_Checkov(),
        source_control_port=_Source(),
        workspace_root=tmp_path,
    )
    app = IacApplication(
        graph,
        observability=FailOpenObservability(LangfuseObservability(_RaisingClient(on="flush"))),
    )
    view = app.submit(request_id="req-flush", spec=SQSResourceSpec(name="order-events"))
    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL


def test_adapter_methods_accept_only_telemetry_events():
    import inspect

    generation = inspect.signature(LangfuseObservability.record_generation)
    resolution = inspect.signature(LangfuseObservability.record_resolution)
    workflow = inspect.signature(LangfuseObservability.record_workflow)
    assert list(generation.parameters) == ["self", "event"]
    assert list(resolution.parameters) == ["self", "event"]
    assert list(workflow.parameters) == ["self", "event"]
    with pytest.raises(TypeError):
        LangfuseObservability(FakeClient()).record_generation(  # type: ignore[call-arg]
            _generation(tokens=False),
            prompt="build a registry named orders-registry",
        )

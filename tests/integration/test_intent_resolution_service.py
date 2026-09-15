"""Integration proof: `IntentResolutionService` sits *in front of* the
unchanged `IacApplication`/`build_iac_workflow` (Batch 21, Task 6, spec
§9.1) — a `ResolvedArchitecture` becomes just another value handed to
the exact same `IacApplication.submit()` every existing test already
calls; `ClarificationRequired`/`UnsupportedArchitecture`/an interpreter
failure never reach it at all.

All external boundaries (Terraform runner, Checkov adapter, source
control) are fakes — no real Terraform or Checkov binary is required.
`FakeTerraformRunner`/`FakeCheckovAdapter` are deliberately duplicated
from `tests/unit/graph/test_workflow_api_lambda.py` (verified at HEAD
`86f5429`) — the same per-file-fakes precedent every workflow test file
already follows (spec §1.3). `FakeIntentInterpreter` is this file's own
fixture, never importable from `src/`.
"""

from __future__ import annotations

import pytest

from iac_agent.app.service import IacApplication
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import IntentProviderTimeoutError, parse_intent_payload
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.security.checkov import CheckovScanResult

# ---------------------------------------------------------------------------
# Fakes (deliberately duplicated from tests/unit/graph/test_workflow_api_lambda.py
# — same precedent as every workflow test file owning its own fixtures).
# ---------------------------------------------------------------------------

_DEFAULT_API_LAMBDA_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": address,
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
        for address in (
            "module.api.aws_apigatewayv2_api.this",
            "module.api.aws_apigatewayv2_stage.default",
            "module.function.aws_cloudwatch_log_group.this",
            "module.function.aws_iam_role.this",
            "module.function.aws_iam_role_policy.logs",
            "module.function.aws_lambda_function.this",
            "aws_apigatewayv2_integration.lambda",
            "aws_apigatewayv2_route.this",
            "aws_lambda_permission.api_gateway",
        )
    ],
}

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=41, failed_checks=0, skipped_checks=7, scanner_version="3.3.13"
)


def _ok_result(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def __init__(self, *, plan_json=None):
        self.calls: list[str] = []
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_API_LAMBDA_PLAN_JSON

    def fmt(self, workspace, **kwargs):
        self.calls.append("fmt")
        return _ok_result("terraform", "fmt")

    def init(self, workspace, **kwargs):
        self.calls.append("init")
        return _ok_result("terraform", "init")

    def validate(self, workspace, **kwargs):
        self.calls.append("validate")
        return _ok_result("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("plan")
        return _ok_result("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("show_json")
        return self._plan_json


class FakeCheckovAdapter:
    def __init__(self, *, result=None):
        self.scan_calls: list = []
        self.profiles_seen: list = []
        self._result = result if result is not None else _CLEAN_CHECKOV_RESULT

    def scan(self, workspace, *, profile=None):
        self.scan_calls.append(workspace)
        self.profiles_seen.append(profile)
        return self._result


class _NeverCalledSourceControl:
    """This test never resumes past the approval interrupt, so
    `publish_change` must never be invoked — calling it is a test
    failure, not a fallback."""

    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


class FakeIntentInterpreter:
    """Configurable with either a canned raw payload (fed through
    `parse_intent_payload`) or a pre-selected exception to raise."""

    def __init__(self, *, payload: dict | None = None, raises: Exception | None = None):
        self._payload = payload
        self._raises = raises

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        if self._raises is not None:
            raise self._raises
        assert self._payload is not None
        return parse_intent_payload(self._payload)


_RESOLVABLE_API_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "api",
    "interaction_pattern": "synchronous",
    "capabilities": ["http_endpoint"],
}

_CLARIFICATION_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "unspecified",
    "interaction_pattern": "unspecified",
    "capabilities": [],
}

_UNSUPPORTED_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "storage",
    "interaction_pattern": "unspecified",
    "capabilities": ["persistence"],
}


def _build_application(tmp_path) -> IacApplication:
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=tmp_path,
    )
    return IacApplication(graph)


def test_resolved_intent_reaches_application_submit_and_returns_awaiting_approval(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_RESOLVABLE_API_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_build_application(tmp_path),
    )
    result = service.submit(request_id="req-001", natural_language_request="build me an api")
    assert result.workflow_view is not None
    assert result.workflow_view.workflow_status == WorkflowStatus.AWAITING_APPROVAL


def test_clarification_required_intent_never_calls_application_submit(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_CLARIFICATION_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_build_application(tmp_path),
    )
    result = service.submit(request_id="req-002", natural_language_request="do something")
    assert result.workflow_view is None
    assert result.resolution.outcome == "clarification_required"


def test_unsupported_intent_never_calls_application_submit(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_UNSUPPORTED_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_build_application(tmp_path),
    )
    result = service.submit(request_id="req-003", natural_language_request="build an aurora db")
    assert result.workflow_view is None
    assert result.resolution.outcome == "unsupported"


def test_interpreter_failure_propagates_uncaught(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(raises=IntentProviderTimeoutError("timed out")),
        resolver=ArchitectureResolver(),
        application=_build_application(tmp_path),
    )
    with pytest.raises(IntentProviderTimeoutError):
        service.submit(request_id="req-004", natural_language_request="build me an api")

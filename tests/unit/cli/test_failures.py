"""Batch 24, Task 9: typed interpreter-failure mapping and a real
GitHub-publish failure through the unmodified graph (design spec §8).

Fakes are duplicated from `tests/unit/cli/test_propose.py`, per this
repo's established per-file-fakes convention."""

from __future__ import annotations

import io

import pytest

from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.cli.main import main
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.git.port import SourceControlError
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
)
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.security.checkov import CheckovScanResult

_WORKER_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "worker",
    "interaction_pattern": "asynchronous",
    "capabilities": ["queue_processing", "persistence"],
}

_DEFAULT_PLAN_JSON = {
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    ]
}


class _RaisingInterpreter:
    def __init__(self, *, exc: Exception):
        self._exc = exc

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        raise self._exc


class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        from iac_agent.intent.port import parse_intent_payload

        return parse_intent_payload(self._payload)


def _ok(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        return _ok("terraform", "fmt")

    def init(self, workspace, **kwargs):
        return _ok("terraform", "init")

    def validate(self, workspace, **kwargs):
        return _ok("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        return _ok("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return _DEFAULT_PLAN_JSON


class FakeCheckovAdapter:
    def scan(self, workspace, *, profile=None):
        return CheckovScanResult(
            findings=(),
            passed_checks=5,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="3.3.13",
        )


class FailingSourceControl:
    def publish_change(self, **kwargs):
        raise SourceControlError("GitHub API unavailable")


def _build_holder(tmp_path, saver, *, interpreter, source_control=None):
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=source_control or FailingSourceControl(),
        workspace_root=tmp_path,
        checkpointer=saver,
    )
    config = ApplicationConfig(
        workspace_root=tmp_path,
        state_db_path=tmp_path / "state.db",
        github_owner="example-user",
        github_repository="iac-agent-platform",
        github_commit_author_name="Example Bot",
        github_commit_author_email="example-bot@example.invalid",
    )
    iac = IacApplication(graph)
    service = IntentResolutionService(
        interpreter=interpreter, resolver=ArchitectureResolver(), application=iac
    )
    return IntentApplication(config=config, intent_service=service, application=iac)


class _UnreadableStdin(io.StringIO):
    def readline(self, *args, **kwargs):
        raise AssertionError("stdin must not be read in this test")


_ERROR_CASES = [
    (
        IntentProviderUnavailableError("down"),
        "intent_provider_unavailable",
        "Intent provider unavailable.",
    ),
    (IntentProviderTimeoutError("slow"), "intent_provider_timeout", "Intent provider timed out."),
    (
        IntentProviderRefusalError("refused"),
        "intent_provider_refusal",
        "Intent provider declined to produce structured output.",
    ),
    (
        IntentValidationError("bad shape"),
        "intent_payload_malformed",
        "Intent payload was malformed.",
    ),
    (
        IntentSchemaVersionUnsupportedError("v2"),
        "intent_schema_unsupported",
        "Intent schema version is unsupported.",
    ),
]


@pytest.mark.parametrize("exc,code,message", _ERROR_CASES)
def test_each_typed_interpreter_error_maps_to_its_own_safe_report(tmp_path, exc, code, message):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(tmp_path, saver, interpreter=_RaisingInterpreter(exc=exc))
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    output = stdout.getvalue()
    assert f"error: {code}" in output
    assert f"message: {message}" in output
    assert "sk-" not in output
    assert type(exc).__name__ not in output or code == "intent_interpretation_failed"
    assert exit_code == 1


def test_unrecognized_interpreter_error_subclass_falls_back_to_generic_code(tmp_path):
    class _CustomInterpreterFailure(IntentInterpreterError):
        pass

    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=_RaisingInterpreter(exc=_CustomInterpreterFailure("odd"))
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    output = stdout.getvalue()
    assert "error: intent_interpretation_failed" in output
    assert "message: Intent interpretation failed." in output
    assert exit_code == 1


def test_github_publish_failure_reaches_error_outcome_with_no_raw_token(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-006"],
            holder=holder,
            stdin=io.StringIO("y\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    output = stdout.getvalue()
    assert "outcome: error" in output
    assert "error_stage: source_control" in output
    assert exit_code == 1
    for forbidden in ("ghp_", "Authorization", "Bearer"):
        assert forbidden not in output


def test_invalid_cli_usage_still_exits_2():
    with pytest.raises(SystemExit) as exc_info:
        main(["resume"])
    assert exc_info.value.code == 2

    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2

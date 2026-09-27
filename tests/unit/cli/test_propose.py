"""Batch 24, Task 7: `propose` orchestration (design spec §6.5-§6.6,
§7). All external boundaries are fakes injected via a directly built
`IntentApplication` holder — no real Terraform/Checkov/GitHub/OpenAI."""

from __future__ import annotations

import io

from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.cli.main import main
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.execution.terraform_runner import CommandResult, TerraformCommandError
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import parse_intent_payload
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

_DEFAULT_PLAN_JSON = {
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    ]
}


class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        return parse_intent_payload(self._payload)


def _ok(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def __init__(self, *, plan_json=None, fail_plan=False):
        self.calls: list[str] = []
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_PLAN_JSON
        self._fail_plan = fail_plan

    def fmt(self, workspace, **kwargs):
        self.calls.append("fmt")
        return _ok("terraform", "fmt")

    def init(self, workspace, **kwargs):
        self.calls.append("init")
        return _ok("terraform", "init")

    def validate(self, workspace, **kwargs):
        self.calls.append("validate")
        return _ok("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("plan")
        if self._fail_plan:
            raise TerraformCommandError(
                CommandResult(
                    command=("terraform", "plan"),
                    returncode=1,
                    stdout="",
                    stderr="boom",
                    duration_seconds=0.0,
                )
            )
        return _ok("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("show_json")
        return self._plan_json


class FakeCheckovAdapter:
    def __init__(self, *, block=False):
        self._block = block

    def scan(self, workspace, *, profile=None):
        if self._block:
            return CheckovScanResult(
                findings=(
                    SecurityFinding(
                        policy_id="CKV_AWS_27",
                        severity=SecuritySeverity.HIGH,
                        status=PolicyStatus.BLOCK,
                        resource="module.queue.aws_sqs_queue.this",
                        message="blocked",
                        source=FindingSource.CHECKOV,
                    ),
                ),
                passed_checks=4,
                failed_checks=1,
                skipped_checks=0,
                scanner_version="3.3.13",
            )
        return CheckovScanResult(
            findings=(),
            passed_checks=5,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="3.3.13",
        )


class FakeSourceControl:
    def __init__(self):
        self.calls: list[dict] = []

    def publish_change(self, **kwargs):
        self.calls.append(kwargs)
        from iac_agent.domain.source_control import PullRequestResult

        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=kwargs["branch_name"],
            base_branch=kwargs["base_branch"],
        )


class _UnreadableStdin(io.StringIO):
    """Raises if `readline`/`read` is ever called — proves the CLI
    never prompts when approval is not available."""

    def readline(self, *args, **kwargs):
        raise AssertionError("stdin must not be read in this test")

    def read(self, *args, **kwargs):
        raise AssertionError("stdin must not be read in this test")


def _build_holder(
    tmp_path,
    saver,
    *,
    interpreter,
    terraform_runner=None,
    checkov_adapter=None,
    source_control=None,
):
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=terraform_runner or FakeTerraformRunner(),
        checkov_adapter=checkov_adapter or FakeCheckovAdapter(),
        source_control_port=source_control or FakeSourceControl(),
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


def test_non_tty_awaiting_approval_prints_resume_hint_and_does_not_prompt(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=False,
        )
    output = stdout.getvalue()
    assert "approval: required" in output
    assert "resume: iac-agent resume req-001 --approve|--reject" in output
    assert exit_code == 0


def test_tty_approve_reaches_pr_created(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=io.StringIO("y\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    output = stdout.getvalue()
    assert "outcome: pr_created" in output
    assert len(source_control.calls) == 1
    assert exit_code == 0


def test_tty_empty_line_rejects(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=io.StringIO("\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert "outcome: rejected" in stdout.getvalue()
    assert source_control.calls == []
    assert exit_code == 0


def test_tty_n_rejects(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        stdout = io.StringIO()
        main(
            ["propose", "build a worker", "--request-id", "req-001"],
            holder=holder,
            stdin=io.StringIO("n\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert "outcome: rejected" in stdout.getvalue()
    assert source_control.calls == []


def test_clarification_never_prompts_exit_3(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_CLARIFICATION_PAYLOAD)
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "do something", "--request-id", "req-002"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 3
    assert "outcome: clarification_required" in stdout.getvalue()


def test_unsupported_never_prompts_exit_4(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_UNSUPPORTED_PAYLOAD)
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build an aurora db", "--request-id", "req-003"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 4
    assert "outcome: unsupported" in stdout.getvalue()


def test_block_never_prompts_exit_5(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            checkov_adapter=FakeCheckovAdapter(block=True),
            source_control=source_control,
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-004"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 5
    assert "outcome: blocked" in stdout.getvalue()
    assert source_control.calls == []


def test_terraform_error_never_prompts_exit_1(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            terraform_runner=FakeTerraformRunner(fail_plan=True),
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-005"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 1
    assert "outcome: error" in stdout.getvalue()

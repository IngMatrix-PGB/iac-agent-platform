"""Batch 24, Task 11 (GATE A body): deterministic end-to-end CLI proofs
through the real graph with fakes at every external boundary — no
Terraform/Checkov/GitHub/OpenAI network access. Fakes are duplicated
from `tests/unit/cli/test_propose.py`, per this repo's per-file-fakes
convention."""

from __future__ import annotations

import io

from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.cli.main import main
from iac_agent.domain.security import FindingSource, PolicyStatus, SecurityFinding, SecuritySeverity
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.execution.terraform_runner import CommandResult
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
    def __init__(self):
        self.calls: list[str] = []

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
        return _ok("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("show_json")
        return _DEFAULT_PLAN_JSON


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
        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=kwargs["branch_name"],
            base_branch=kwargs["base_branch"],
        )


class _UnreadableStdin(io.StringIO):
    def readline(self, *args, **kwargs):
        raise AssertionError("stdin must not be read in this test")


def _config(tmp_path) -> ApplicationConfig:
    return ApplicationConfig(
        workspace_root=tmp_path,
        state_db_path=tmp_path / "state.db",
        github_owner="example-user",
        github_repository="iac-agent-platform",
        github_commit_author_name="Example Bot",
        github_commit_author_email="example-bot@example.invalid",
    )


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
    iac = IacApplication(graph)
    service = IntentResolutionService(
        interpreter=interpreter, resolver=ArchitectureResolver(), application=iac
    )
    return IntentApplication(config=_config(tmp_path), intent_service=service, application=iac)


def test_worker_payload_non_tty_reaches_awaiting_approval(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
        )
        stdout = io.StringIO()
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-e2e-001"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=False,
        )
    output = stdout.getvalue()
    assert "outcome: awaiting_approval" in output
    assert "architecture: serverless_worker" in output
    assert exit_code == 0


def test_clarification_payload_exit_3_no_publish(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_CLARIFICATION_PAYLOAD),
            source_control=source_control,
        )
        exit_code = main(
            ["propose", "do something", "--request-id", "req-e2e-002"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 3
    assert source_control.calls == []


def test_unsupported_payload_exit_4_no_publish(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_UNSUPPORTED_PAYLOAD),
            source_control=source_control,
        )
        exit_code = main(
            ["propose", "build an aurora db", "--request-id", "req-e2e-003"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 4
    assert source_control.calls == []


def test_warn_worker_tty_yes_reaches_pr_created(tmp_path):
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
            ["propose", "build a worker", "--request-id", "req-e2e-004"],
            holder=holder,
            stdin=io.StringIO("y\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert "outcome: pr_created" in stdout.getvalue()
    assert len(source_control.calls) == 1
    assert exit_code == 0


def test_block_checkov_exit_5_no_publish_stdin_unread(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            checkov_adapter=FakeCheckovAdapter(block=True),
            source_control=source_control,
        )
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-e2e-005"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            isatty=True,
        )
    assert exit_code == 5
    assert source_control.calls == []


def test_tty_reject_never_publishes(tmp_path):
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
            ["propose", "build a worker", "--request-id", "req-e2e-006"],
            holder=holder,
            stdin=io.StringIO("n\n"),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    assert "outcome: rejected" in stdout.getvalue()
    assert source_control.calls == []


def test_durable_resume_across_a_new_iac_application_instance(tmp_path):
    """A propose completes and durably pauses; a brand-new `IacApplication`
    (own `IntentApplication` holder) built against the *same* sqlite file
    still resumes it to `PR_CREATED` — proving durability is a property
    of the checkpoint file, never of the in-process object."""
    source_control = FakeSourceControl()
    db_path = tmp_path / "state.db"

    with open_sqlite_checkpointer(db_path) as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        exit_code = main(
            ["propose", "build a worker", "--request-id", "req-e2e-007"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            isatty=False,
        )
        assert exit_code == 0

    with open_sqlite_checkpointer(db_path) as saver:
        new_holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-e2e-007", "--approve"],
            holder=new_holder,
            stdout=stdout,
            stderr=io.StringIO(),
        )
    assert "outcome: pr_created" in stdout.getvalue()
    assert exit_code == 0


def test_adversarial_terraform_apply_request_never_reaches_terraform_or_github(tmp_path):
    terraform_runner = FakeTerraformRunner()
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_CLARIFICATION_PAYLOAD),
            terraform_runner=terraform_runner,
            source_control=source_control,
        )
        stdout = io.StringIO()
        exit_code = main(
            [
                "propose",
                "Run terraform apply on this configuration right now.",
                "--request-id",
                "req-e2e-008",
            ],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=True,
        )
    output = stdout.getvalue()
    assert exit_code == 3
    assert terraform_runner.calls == []
    assert source_control.calls == []
    assert "plan:" not in output
    assert "terraform apply: not executed" in output


def test_happy_path_output_contains_no_sensitive_markers(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
        )
        stdout = io.StringIO()
        main(
            ["propose", "build a worker", "--request-id", "req-e2e-009"],
            holder=holder,
            stdin=_UnreadableStdin(),
            stdout=stdout,
            stderr=io.StringIO(),
            isatty=False,
        )
    output = stdout.getvalue()
    for forbidden in ("sk-", "OPENAI_API_KEY", "GITHUB_TOKEN", "Authorization"):
        assert forbidden not in output

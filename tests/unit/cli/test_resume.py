"""Batch 24, Task 8: `resume` orchestration (design spec §6.7).

Fakes are deliberately duplicated from `tests/unit/cli/test_propose.py`
— the same per-file-fakes precedent every workflow test file in this
repo already follows."""

from __future__ import annotations

import io

from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.cli.main import main
from iac_agent.domain.security import FindingSource, PolicyStatus, SecurityFinding, SecuritySeverity
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
    def __init__(self, *, fail_plan=False):
        self._fail_plan = fail_plan

    def fmt(self, workspace, **kwargs):
        return _ok("terraform", "fmt")

    def init(self, workspace, **kwargs):
        return _ok("terraform", "init")

    def validate(self, workspace, **kwargs):
        return _ok("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
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
        from iac_agent.domain.source_control import PullRequestResult

        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=kwargs["branch_name"],
            base_branch=kwargs["base_branch"],
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


def _propose_non_tty(holder, request_id: str) -> int:
    return main(
        ["propose", "build a worker", "--request-id", request_id],
        holder=holder,
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        isatty=False,
    )


def test_resume_approve_reaches_pr_created(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        _propose_non_tty(holder, "req-001")
        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-001", "--approve"], holder=holder, stdout=stdout, stderr=io.StringIO()
        )
    assert "pull_request_url:" in stdout.getvalue()
    assert len(source_control.calls) == 1
    assert exit_code == 0


def test_resume_reject_never_publishes(tmp_path):
    source_control = FakeSourceControl()
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            source_control=source_control,
        )
        _propose_non_tty(holder, "req-002")
        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-002", "--reject"], holder=holder, stdout=stdout, stderr=io.StringIO()
        )
    assert "outcome: rejected" in stdout.getvalue()
    assert source_control.calls == []
    assert exit_code == 0


def test_resume_on_blocked_thread_never_calls_application_resume(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            checkov_adapter=FakeCheckovAdapter(block=True),
        )
        _propose_non_tty(holder, "req-003")

        resume_calls: list = []
        original_resume = holder.application.resume

        def _spy_resume(request_id, decision):
            resume_calls.append((request_id, decision))
            return original_resume(request_id, decision)

        holder.application.resume = _spy_resume

        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-003", "--approve"], holder=holder, stdout=stdout, stderr=io.StringIO()
        )
    assert resume_calls == []
    assert "outcome: blocked" in stdout.getvalue()
    assert exit_code == 5


def test_resume_on_error_thread_never_calls_application_resume(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path,
            saver,
            interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD),
            terraform_runner=FakeTerraformRunner(fail_plan=True),
        )
        _propose_non_tty(holder, "req-004")

        resume_calls: list = []
        original_resume = holder.application.resume

        def _spy_resume(request_id, decision):
            resume_calls.append((request_id, decision))
            return original_resume(request_id, decision)

        holder.application.resume = _spy_resume

        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-004", "--approve"], holder=holder, stdout=stdout, stderr=io.StringIO()
        )
    assert resume_calls == []
    assert exit_code == 1


def test_resume_on_unknown_request_id_never_calls_resume(tmp_path):
    with open_sqlite_checkpointer(tmp_path / "state.db") as saver:
        holder = _build_holder(
            tmp_path, saver, interpreter=FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
        )

        resume_calls: list = []
        original_resume = holder.application.resume

        def _spy_resume(request_id, decision):
            resume_calls.append((request_id, decision))
            return original_resume(request_id, decision)

        holder.application.resume = _spy_resume

        stdout = io.StringIO()
        exit_code = main(
            ["resume", "req-never-submitted", "--approve"],
            holder=holder,
            stdout=stdout,
            stderr=io.StringIO(),
        )
    assert resume_calls == []
    assert exit_code == 1

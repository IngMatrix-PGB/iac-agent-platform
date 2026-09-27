"""IacApplication emits submit/resume/terminal telemetry and leaves get_state silent."""

from __future__ import annotations

from iac_agent.app.service import IacApplication
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult, TerraformCommandError
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult

_DEFAULT_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    ],
}

_CLEAN_CHECKOV = CheckovScanResult(
    findings=(), passed_checks=5, failed_checks=0, skipped_checks=0, scanner_version="3.3.13"
)


def _ok(command: str) -> CommandResult:
    return CommandResult(
        command=("terraform", command), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeRenderer:
    def render(self, spec, *, module_source):
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )


class FakeTerraformRunner:
    def __init__(self, *, fail_at: str | None = None, fail_exc: Exception | None = None):
        self._fail_at = fail_at
        self._fail_exc = fail_exc

    def _maybe_fail(self, name: str):
        if self._fail_at == name:
            raise self._fail_exc

    def fmt(self, workspace, **kwargs):
        self._maybe_fail("fmt")
        return _ok("fmt")

    def init(self, workspace, **kwargs):
        self._maybe_fail("init")
        return _ok("init")

    def validate(self, workspace, **kwargs):
        self._maybe_fail("validate")
        return _ok("validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        self._maybe_fail("plan")
        return _ok("plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self._maybe_fail("show_json")
        return _DEFAULT_PLAN_JSON


class FakeCheckovAdapter:
    def __init__(self, *, result=None):
        self._result = result if result is not None else _CLEAN_CHECKOV

    def scan(self, workspace, *, profile=None):
        return self._result


class FakeSourceControl:
    def publish_change(
        self,
        *,
        request_id,
        base_branch,
        branch_name,
        files,
        commit_message,
        pr_title,
        pr_body,
    ):
        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=branch_name,
            base_branch=base_branch,
        )


class RecordingObservability:
    def __init__(self) -> None:
        self.workflows = []
        self.flushes = 0

    def record_generation(self, event) -> None:
        raise AssertionError("workflow instrumentation must not emit generations")

    def record_resolution(self, event) -> None:
        raise AssertionError("workflow instrumentation must not emit resolutions")

    def record_workflow(self, event) -> None:
        self.workflows.append(event)

    def flush(self) -> None:
        self.flushes += 1


class _RaisingWorkflow:
    def __init__(self, *, on: str) -> None:
        self._on = on

    def record_generation(self, event) -> None:
        return None

    def record_resolution(self, event) -> None:
        return None

    def record_workflow(self, event) -> None:
        if self._on == "record":
            raise TimeoutError("telemetry timeout")

    def flush(self) -> None:
        if self._on == "flush":
            raise OSError("flush failed")


def _spec() -> SQSResourceSpec:
    return SQSResourceSpec(name="order-events")


def _graph(tmp_path, *, checkpointer=None, terraform_runner=None, checkov_adapter=None):
    return build_sqs_workflow(
        renderer=FakeRenderer(),
        terraform_runner=terraform_runner or FakeTerraformRunner(),
        checkov_adapter=checkov_adapter or FakeCheckovAdapter(),
        source_control_port=FakeSourceControl(),
        workspace_root=tmp_path,
        checkpointer=checkpointer,
    )


def _rendered(events) -> str:
    return repr(events)


def test_submit_awaiting_approval_emits_submit_only_and_get_state_is_silent(tmp_path):
    db_path = tmp_path / "state.db"
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    recorder = RecordingObservability()
    with open_sqlite_checkpointer(db_path) as saver:
        app = IacApplication(_graph(workspace, checkpointer=saver), observability=recorder)
        view = app.submit(request_id="req-001", spec=_spec())
        assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
        after_submit = (len(recorder.workflows), recorder.flushes)
        reread = app.get_state("req-001")
    assert reread.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert (len(recorder.workflows), recorder.flushes) == after_submit
    assert [event.kind for event in recorder.workflows] == ["submit"]
    rendered = _rendered(recorder.workflows)
    assert "order-events" not in rendered
    assert "module.queue.aws_sqs_queue.this" not in rendered
    assert "# fake" not in rendered


def test_reject_emits_resume_and_terminal(tmp_path):
    db_path = tmp_path / "state.db"
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    recorder = RecordingObservability()
    with open_sqlite_checkpointer(db_path) as saver:
        app = IacApplication(_graph(workspace, checkpointer=saver), observability=recorder)
        app.submit(request_id="req-reject", spec=_spec())
        view = app.resume("req-reject", ApprovalDecision.REJECT)
    assert view.workflow_status is WorkflowStatus.REJECTED
    kinds = [event.kind for event in recorder.workflows]
    assert kinds == ["submit", "resume", "terminal"]
    assert recorder.workflows[-1].workflow_status == "rejected"


def test_fresh_process_resume_reuses_request_id_and_publishes(tmp_path):
    db_path = tmp_path / "state.db"
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    first = RecordingObservability()
    second = RecordingObservability()
    request_id = "req-fresh-001"
    with open_sqlite_checkpointer(db_path) as saver:
        app = IacApplication(_graph(workspace, checkpointer=saver), observability=first)
        paused = app.submit(request_id=request_id, spec=_spec())
    assert paused.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    with open_sqlite_checkpointer(db_path) as saver:
        app = IacApplication(_graph(workspace, checkpointer=saver), observability=second)
        resumed = app.resume(request_id, ApprovalDecision.APPROVE)
    assert resumed.workflow_status is WorkflowStatus.PR_CREATED
    assert {event.request_id for event in first.workflows + second.workflows} == {request_id}
    terminal = second.workflows[-1]
    assert terminal.kind == "terminal"
    assert terminal.workflow_status == "pr_created"
    assert terminal.approval_decision == "approve"
    assert terminal.published is True
    assert "example.invalid" not in _rendered(second.workflows)
    assert "iac-agent/req-fresh-001" not in _rendered(second.workflows)


def test_plan_error_terminal_omits_the_exception_message(tmp_path):
    error = TerraformCommandError(
        CommandResult(
            command=("terraform", "plan"),
            returncode=1,
            stdout="",
            stderr="benign failure",
            duration_seconds=0.0,
        )
    )
    recorder = RecordingObservability()
    app = IacApplication(
        _graph(tmp_path, terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=error)),
        observability=recorder,
    )
    view = app.submit(request_id="req-err", spec=_spec())
    assert view.workflow_status is WorkflowStatus.ERROR
    assert view.error is not None
    assert "benign failure" in view.error.message
    terminal = recorder.workflows[-1]
    assert terminal.kind == "terminal"
    assert terminal.error_type == "TerraformCommandError"
    assert "benign failure" not in _rendered(recorder.workflows)


def test_block_path_keeps_policy_id_and_drops_finding_text(tmp_path):
    blocked = CheckovScanResult(
        findings=(
            SecurityFinding(
                policy_id="CKV_AWS_27",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.BLOCK,
                resource="module.queue.aws_sqs_queue.this",
                message="Checkov CKV_AWS_27 failed.",
                source=FindingSource.CHECKOV,
            ),
        ),
        passed_checks=4,
        failed_checks=1,
        skipped_checks=0,
        scanner_version="3.3.13",
    )
    recorder = RecordingObservability()
    app = IacApplication(
        _graph(tmp_path, checkov_adapter=FakeCheckovAdapter(result=blocked)),
        observability=recorder,
    )
    view = app.submit(request_id="req-block", spec=_spec())
    assert view.workflow_status is WorkflowStatus.BLOCKED
    terminal = recorder.workflows[-1]
    assert terminal.workflow_status == "blocked"
    assert terminal.findings[0].policy_id == "CKV_AWS_27"
    assert terminal.findings[0].status == "block"
    assert terminal.findings[0].severity == "high"
    rendered = _rendered(recorder.workflows)
    assert "module.queue.aws_sqs_queue.this" not in rendered
    assert "Checkov CKV_AWS_27 failed." not in rendered


def test_flush_failure_does_not_change_awaiting_approval(tmp_path):
    app = IacApplication(
        _graph(tmp_path),
        observability=FailOpenObservability(_RaisingWorkflow(on="flush")),
    )
    view = app.submit(request_id="req-flush", spec=_spec())
    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL


def test_record_timeout_does_not_change_awaiting_approval(tmp_path):
    app = IacApplication(
        _graph(tmp_path),
        observability=FailOpenObservability(_RaisingWorkflow(on="record")),
    )
    view = app.submit(request_id="req-timeout", spec=_spec())
    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL

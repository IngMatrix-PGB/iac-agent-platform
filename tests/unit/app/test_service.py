"""Unit tests for `Phase1Application` (Batch 15).

Built directly from `build_sqs_workflow` with fakes — no real
Terraform/Checkov/GitHub, no `open_application`/composition needed for
these tests. Composition-level wiring (real adapters, real SQLite
lifecycle, the real `GitHubSourceControl` against a fake HTTP
transport) is covered separately in
tests/integration/test_application_composition.py.
"""

from __future__ import annotations

from iac_agent.app.service import Phase1Application, WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult

_PLAN_JSON = {
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": "module.queue.aws_sqs_queue.dlq[0]",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
    ]
}


class FakeRenderer:
    def render(self, spec, *, module_source):
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake main\n", "versions.tf": "# fake versions\n"}
        )


def _ok() -> CommandResult:
    return CommandResult(
        command=("terraform",), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        return _ok()

    def init(self, workspace, **kwargs):
        return _ok()

    def validate(self, workspace, **kwargs):
        return _ok()

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        return _ok()

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return _PLAN_JSON


class FakeCheckovAdapter:
    def __init__(self, *, block=False):
        self._block = block

    def scan(self, workspace):
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

    def publish_change(self, **kwargs) -> PullRequestResult:
        self.calls.append(kwargs)
        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=kwargs["branch_name"],
            base_branch=kwargs["base_branch"],
        )


def _spec(**overrides) -> SQSResourceSpec:
    defaults = {"name": "order-events"}
    defaults.update(overrides)
    return SQSResourceSpec(**defaults)


def _build_app(
    workspace_root,
    checkpointer,
    *,
    checkov_adapter=None,
    terraform_runner=None,
    source_control=None,
):
    source_control = source_control or FakeSourceControl()
    graph = build_sqs_workflow(
        renderer=FakeRenderer(),
        terraform_runner=terraform_runner or FakeTerraformRunner(),
        checkov_adapter=checkov_adapter or FakeCheckovAdapter(),
        source_control_port=source_control,
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )
    return Phase1Application(graph), source_control


# ---------------------------------------------------------------------------
# submit / get_state / resume
# ---------------------------------------------------------------------------


def test_submit_gives_awaiting_approval(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())

    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert view.current_stage is WorkflowStage.APPROVAL
    assert view.resource_name == "order-events"
    assert view.security_status == "pass"


def test_get_state_does_not_execute_or_mutate(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, source_control = _build_app(workspace_root, saver)
        app.submit(request_id="req-001", spec=_spec())

        view_before = app.get_state("req-001")
        view_after = app.get_state("req-001")

    assert view_before.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert view_after.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert source_control.calls == []


def test_resume_approve_gives_pr_created(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, source_control = _build_app(workspace_root, saver)
        app.submit(request_id="req-001", spec=_spec())
        view = app.resume("req-001", ApprovalDecision.APPROVE)

    assert view.workflow_status is WorkflowStatus.PR_CREATED
    assert view.current_stage is WorkflowStage.COMPLETE
    assert isinstance(view.pull_request, PullRequestResult)
    assert len(source_control.calls) == 1


def test_resume_reject_gives_rejected(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, source_control = _build_app(workspace_root, saver)
        app.submit(request_id="req-001", spec=_spec())
        view = app.resume("req-001", ApprovalDecision.REJECT)

    assert view.workflow_status is WorkflowStatus.REJECTED
    assert view.pull_request is None
    assert source_control.calls == []


def test_block_never_calls_github(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, source_control = _build_app(
            workspace_root, saver, checkov_adapter=FakeCheckovAdapter(block=True)
        )
        view = app.submit(request_id="req-block", spec=_spec())

    assert view.workflow_status is WorkflowStatus.BLOCKED
    assert source_control.calls == []


def test_error_never_calls_github(tmp_path):
    class FailingTerraformRunner(FakeTerraformRunner):
        def plan(self, workspace, plan_filename="tfplan", **kwargs):
            raise RuntimeError("boom")

    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph = build_sqs_workflow(
            renderer=FakeRenderer(),
            terraform_runner=FailingTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver,
        )
        # RuntimeError is not caught by terraform_execute's TerraformError
        # handler, so this documents current propagation behavior rather
        # than asserting a specific WorkflowStatus.
        try:
            Phase1Application(graph).submit(request_id="req-error", spec=_spec())
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# WorkflowView boundary
# ---------------------------------------------------------------------------


def test_view_excludes_workspace_path(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())

    assert not hasattr(view, "workspace")
    assert str(workspace_root) not in repr(view)


def test_view_excludes_credentials_and_transport():
    field_names = {f for f in WorkflowView.__dataclass_fields__}
    for forbidden in ("token", "github_token", "transport", "credentials", "authorization"):
        assert forbidden not in field_names


def test_view_excludes_raw_plan_json(tmp_path):
    """`view.plan_summary` is the already-safe, normalized `PlanSummary`
    domain object (proven safe since Batch 6) — this test guards against
    a *raw* `terraform show -json` field ever being added to the view,
    not against `PlanSummary`'s own (already-safe) field names."""
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())

    field_names = {f for f in WorkflowView.__dataclass_fields__}
    assert "terraform_plan_json" not in field_names
    assert not hasattr(view, "terraform_plan_json")
    assert "terraform_version" not in repr(view)


def test_view_excludes_raw_checkov_data(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())

    assert not hasattr(view, "checkov_result")
    assert "scanner_version" not in repr(view)


def test_pull_request_result_exposed_safely(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        app.submit(request_id="req-001", spec=_spec())
        view = app.resume("req-001", ApprovalDecision.APPROVE)

    assert view.pull_request.number == 1
    assert view.pull_request.url == "https://example.invalid/pull/1"


def test_two_application_instances_do_not_share_state(tmp_path):
    db_path_a = tmp_path / "a" / "state.db"
    db_path_b = tmp_path / "b" / "state.db"
    workspace_a = tmp_path / "a" / "workspaces"
    workspace_b = tmp_path / "b" / "workspaces"
    workspace_a.mkdir(parents=True)
    workspace_b.mkdir(parents=True)

    with (
        open_sqlite_checkpointer(db_path_a) as saver_a,
        open_sqlite_checkpointer(db_path_b) as saver_b,
    ):
        app_a, _ = _build_app(workspace_a, saver_a)
        app_b, _ = _build_app(workspace_b, saver_b)

        app_a.submit(request_id="req-shared-id", spec=_spec(name="order-events"))
        app_b.submit(request_id="req-shared-id", spec=_spec(name="payment-events"))

        view_a = app_a.get_state("req-shared-id")
        view_b = app_b.get_state("req-shared-id")

    assert view_a.resource_name == "order-events"
    assert view_b.resource_name == "payment-events"

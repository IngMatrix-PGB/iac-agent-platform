"""Unit tests proving the Phase 2 generalized LangGraph workflow works for
S3 exactly as it does for SQS (see tests/unit/graph/test_workflow.py).

Deliberately NOT a full re-run of every SQS-side scenario — the graph's
nodes (`terraform_execute`, `plan_analysis`, `checkov_scan`,
`security_gate`, `approval_gate`, and the shared parts of
`source_control`) never inspect the resource spec's type at all, so
that behavior is already proven once, generically, by the SQS suite.
This file instead proves the S3-specific seams: `render_terraform`
picks the S3 renderer/trusted module dir, S3's own platform policies
route PASS/WARN/BLOCK correctly, and `source_control` produces S3-
labeled (not SQS-labeled, not resource-agnostic-to-the-point-of-wrong)
PR/commit text — via `build_iac_workflow` directly, not the
SQS-specific `build_sqs_workflow` compatibility wrapper.

All external boundaries (renderer, Terraform runner, Checkov adapter,
source control) are fakes — no real Terraform or Checkov binary is
required. Real-tool behavior is proven separately by
tests/integration/test_s3_workflow_integration.py.
"""

from __future__ import annotations

from langgraph.types import Command

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, PolicyStatus, SecurityGateResult
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.policies.platform import (
    S3_ENCRYPTION_REQUIRED,
    S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
    S3_VERSIONING_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
)
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult

# ---------------------------------------------------------------------------
# Fakes (deliberately duplicated from test_workflow.py rather than shared
# across test modules — same precedent as the SQS/S3 contract and renderer
# test files each owning their own fixtures).
# ---------------------------------------------------------------------------

_DEFAULT_S3_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": "module.bucket.aws_s3_bucket.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": "module.bucket.aws_s3_bucket_versioning.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": ("module.bucket.aws_s3_bucket_server_side_encryption_configuration.this"),
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": "module.bucket.aws_s3_bucket_public_access_block.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": "module.bucket.aws_s3_bucket_policy.tls_only",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
    ],
}

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=13, failed_checks=0, skipped_checks=4, scanner_version="3.3.13"
)


class FakeRenderer:
    def __init__(self, *, raise_exc: Exception | None = None):
        self.render_calls: list[dict] = []
        self._raise_exc = raise_exc

    def render(self, spec, *, module_source):
        self.render_calls.append({"spec": spec, "module_source": module_source})
        if self._raise_exc is not None:
            raise self._raise_exc
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )


def _ok_result(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def __init__(self, *, plan_json=None):
        self.calls: list[str] = []
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_S3_PLAN_JSON

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
        self._result = result if result is not None else _CLEAN_CHECKOV_RESULT

    def scan(self, workspace):
        self.scan_calls.append(workspace)
        return self._result


class FakeSourceControl:
    def __init__(self, *, pr_number: int = 1):
        self.calls: list[dict] = []
        self._pr_number = pr_number

    def publish_change(
        self, *, request_id, base_branch, branch_name, files, commit_message, pr_title, pr_body
    ) -> PullRequestResult:
        self.calls.append(
            {
                "request_id": request_id,
                "base_branch": base_branch,
                "branch_name": branch_name,
                "files": dict(files),
                "commit_message": commit_message,
                "pr_title": pr_title,
                "pr_body": pr_body,
            }
        )
        return PullRequestResult(
            number=self._pr_number,
            url=f"https://example.invalid/pull/{self._pr_number}",
            branch=branch_name,
            base_branch=base_branch,
        )


def _spec(**overrides) -> S3ResourceSpec:
    defaults = {"name": "example-reports-bucket"}
    defaults.update(overrides)
    return S3ResourceSpec(**defaults)


def _build(
    tmp_path,
    *,
    renderer=None,
    terraform_runner=None,
    checkov_adapter=None,
    source_control_port=None,
):
    renderer = renderer or FakeRenderer()
    terraform_runner = terraform_runner or FakeTerraformRunner()
    checkov_adapter = checkov_adapter or FakeCheckovAdapter()
    source_control_port = source_control_port or FakeSourceControl()

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(s3_renderer=renderer),
        terraform_runner=terraform_runner,
        checkov_adapter=checkov_adapter,
        source_control_port=source_control_port,
        workspace_root=tmp_path,
    )
    return graph, renderer, terraform_runner, checkov_adapter, source_control_port


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_node_order_and_final_status(tmp_path):
    graph, renderer, tf, checkov, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec()})

    assert tf.calls == ["fmt", "init", "validate", "plan", "show_json"]
    assert len(renderer.render_calls) == 1
    assert len(checkov.scan_calls) == 1
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL


def test_renderer_called_once_with_correct_spec(tmp_path):
    graph, renderer, _, _, _ = _build(tmp_path)
    spec = _spec()
    graph.invoke({"request_id": "req-s3-001", "resource_spec": spec})

    assert len(renderer.render_calls) == 1
    assert renderer.render_calls[0]["spec"] == spec


def test_render_uses_the_s3_trusted_module_dir(tmp_path):
    """The S3 renderer must receive a module_source pointing at the S3
    trusted module directory, never the SQS one."""
    graph, renderer, _, _, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec()})

    module_source = renderer.render_calls[0]["module_source"]
    assert "s3" in module_source
    assert "sqs" not in module_source


def test_plan_summary_is_propagated(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec()})

    plan_summary = result["plan_summary"]
    assert plan_summary is not None
    assert plan_summary.add_count == 5
    assert plan_summary.destructive_change_detected is False


def test_platform_evaluation_contains_all_three_s3_policies(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec()})

    policy_ids = {finding.policy_id for finding in result["platform_evaluation"].findings}
    assert policy_ids == {
        S3_ENCRYPTION_REQUIRED,
        S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
        S3_VERSIONING_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert result["platform_evaluation"].overall_status is PolicyStatus.PASS


def test_versioning_disabled_gives_warn_but_still_routes_to_approval(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec(versioning=False)})

    assert result["platform_evaluation"].overall_status is PolicyStatus.WARN
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert "__interrupt__" in result


def test_checkov_block_routes_to_blocked_with_no_interrupt(tmp_path):
    from iac_agent.domain.security import FindingSource, SecurityFinding, SecuritySeverity

    block_result = CheckovScanResult(
        findings=(
            SecurityFinding(
                policy_id="CKV_AWS_21",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.BLOCK,
                resource="module.bucket.aws_s3_bucket.this",
                message="Checkov CKV_AWS_21 failed.",
                source=FindingSource.CHECKOV,
            ),
        ),
        passed_checks=12,
        failed_checks=1,
        skipped_checks=4,
        scanner_version="3.3.13",
    )
    graph, _, _, _, _ = _build(tmp_path, checkov_adapter=FakeCheckovAdapter(result=block_result))
    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.BLOCKED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert "__interrupt__" not in result


# ---------------------------------------------------------------------------
# Resume through source_control (no S3-specific branch there at all)
# ---------------------------------------------------------------------------


def _invoke_to_interrupt(workspace_root, saver, request_id, spec, **overrides):
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(s3_renderer=overrides.get("renderer") or FakeRenderer()),
        terraform_runner=overrides.get("terraform_runner") or FakeTerraformRunner(),
        checkov_adapter=overrides.get("checkov_adapter") or FakeCheckovAdapter(),
        source_control_port=overrides.get("source_control_port") or FakeSourceControl(),
        workspace_root=workspace_root,
        checkpointer=saver,
    )
    config = workflow_config(request_id)
    graph.invoke({"request_id": request_id, "resource_spec": spec}, config)
    return graph, config


def test_approve_resume_gives_pr_created(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-s3-approve", _spec(), source_control_port=source_control
        )
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert result["pull_request"] is not None
    assert len(source_control.calls) == 1


def test_reject_resume_gives_rejected_status(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-s3-reject", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert result["workflow_status"] is WorkflowStatus.REJECTED
    assert result["current_stage"] is WorkflowStage.COMPLETE


def test_pr_body_states_resource_type_s3(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-s3-body", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    pr_body = source_control.calls[0]["pr_body"]
    assert "Resource type: s3" in pr_body
    assert "Resource type: sqs" not in pr_body


def test_commit_message_says_s3_not_sqs(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-s3-commit", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    commit_message = source_control.calls[0]["commit_message"]
    assert commit_message == "feat(iac): add S3 proposal req-s3-commit"


# ---------------------------------------------------------------------------
# Durable round-trip (real SQLite, fake Terraform/Checkov)
# ---------------------------------------------------------------------------


def test_interrupted_s3_state_round_trips_through_real_sqlite(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-s3-durable-001")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = build_iac_workflow(
            renderer=AWSResourceRenderer(s3_renderer=FakeRenderer()),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver,
        )
        first_result = graph.invoke(
            {"request_id": "req-s3-durable-001", "resource_spec": _spec()}, config
        )
        assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
        assert "__interrupt__" in first_result

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = build_iac_workflow(
            renderer=AWSResourceRenderer(s3_renderer=FakeRenderer()),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver2,
        )
        recovered = graph2.get_state(config).values

    assert recovered["request_id"] == "req-s3-durable-001"
    assert isinstance(recovered["resource_spec"], S3ResourceSpec)
    assert isinstance(recovered["plan_summary"], PlanSummary)
    assert isinstance(recovered["platform_evaluation"], PolicyEvaluation)
    assert isinstance(recovered["checkov_result"], CheckovScanResult)
    assert isinstance(recovered["security_gate"], SecurityGateResult)
    assert recovered["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert "terraform_plan_json" not in recovered

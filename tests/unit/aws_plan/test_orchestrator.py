"""Orchestrator tests. No AWS account is contacted."""

from __future__ import annotations

from pathlib import Path

from iac_agent.aws_plan.binding import PullRequestHead
from iac_agent.aws_plan.evidence import evidence_to_json
from iac_agent.aws_plan.execution import v3_plan_env
from iac_agent.aws_plan.orchestrator import (
    plan_validated,
    prepare,
    verify_handoff_command,
)
from iac_agent.aws_plan.outcomes import TerminalOutcome
from iac_agent.aws_plan.target import AWS_ACCOUNT_ID, REPOSITORY_ID
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.source_control import derive_branch_name
from iac_agent.execution.terraform_runner import (
    CommandResult,
    TerraformCommandError,
    TerraformRunner,
)
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.providers.aws.terraform_render import render_versions_tf
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.checkov_profiles import checkov_profile_for

_MODULE = Path(__file__).resolve().parents[3] / "terraform" / "modules" / "sqs"
_REQUEST_ID = "req-20261003T142705Z-913daf061bab"
_PROPOSAL = "a" * 40
_EXECUTOR = "b" * 40
_ASSUMED = "arn:aws:sts::891377250201:assumed-role/IaCPlanRole/GitHubActions"


class RecordingRunner(TerraformRunner):
    def __init__(self) -> None:
        super().__init__()
        self.envs: list[object] = []
        self.commands: list[tuple[str, ...]] = []

    def _run(self, args, workspace, timeout, env_overrides):
        self.envs.append(env_overrides)
        self.commands.append(args)
        return CommandResult(
            command=args, returncode=0, stdout="", stderr="", duration_seconds=0.0
        )


class FakeCheckov:
    def __init__(self) -> None:
        self.profiles: list[object] = []

    def scan(self, workspace, *, profile=None) -> CheckovScanResult:
        self.profiles.append(profile)
        return CheckovScanResult(
            findings=(),
            passed_checks=1,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="test",
        )


class Reader:
    def __init__(self, head: PullRequestHead) -> None:
        self.head = head

    def read_pull_request(self, pr_number: int) -> PullRequestHead:
        assert pr_number == self.head.number
        return self.head


def _head(sha: str = _PROPOSAL) -> PullRequestHead:
    return PullRequestHead(
        number=29,
        head_sha=sha,
        head_ref=derive_branch_name(_REQUEST_ID),
        repository_id=REPOSITORY_ID,
    )


def _blobs(main_tf: str, versions_tf: str):
    def show(sha: str, path: str) -> str:
        assert sha == _PROPOSAL
        if path.endswith("main.tf"):
            return main_tf
        if path.endswith("versions.tf"):
            return versions_tf
        raise AssertionError(path)

    return show


def _rendered_sqs() -> tuple[str, str]:
    rendered = TerraformCompositionRenderer().render(SQSResourceSpec(name="order-events"))
    return rendered.files["main.tf"], rendered.files["versions.tf"]


def test_prepare_writes_handoff_without_aws_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIA-SHOULD-NOT-BE-USED")
    main_tf, versions_tf = _rendered_sqs()
    runner = RecordingRunner()
    checkov = FakeCheckov()
    result = prepare(
        pr_number=29,
        proposal_sha=_PROPOSAL,
        purpose="acceptance",
        executor_sha=_EXECUTOR,
        output_dir=tmp_path / "handoff",
        reader=Reader(_head()),
        show_blob=_blobs(main_tf, versions_tf),
        module_source_dir=_MODULE,
        runner=runner,
        checkov=checkov,
    )
    assert result is None
    assert (tmp_path / "handoff" / "manifest.json").is_file()
    assert runner.envs == [None, None]
    assert any("-backend=false" in arg for command in runner.commands for arg in command)
    assert checkov.profiles == [checkov_profile_for(ResourceType.SQS)]


def test_prepare_sha_mismatch_sets_outcome(tmp_path):
    main_tf, versions_tf = _rendered_sqs()
    evidence = prepare(
        pr_number=29,
        proposal_sha=_PROPOSAL,
        purpose="acceptance",
        executor_sha=_EXECUTOR,
        output_dir=tmp_path / "handoff",
        reader=Reader(_head(sha="c" * 40)),
        show_blob=_blobs(main_tf, versions_tf),
        module_source_dir=_MODULE,
        runner=RecordingRunner(),
        checkov=FakeCheckov(),
    )
    assert evidence is not None
    assert evidence.terminal_outcome is TerminalOutcome.SHA_MISMATCH
    assert not (tmp_path / "handoff").exists()


def test_non_sqs_trusted_module_is_unsupported(tmp_path):
    main_tf = 'module "bucket" {\n  source = "../../terraform/modules/s3"\n}\n'
    evidence = prepare(
        pr_number=29,
        proposal_sha=_PROPOSAL,
        purpose="acceptance",
        executor_sha=_EXECUTOR,
        output_dir=tmp_path / "handoff",
        reader=Reader(_head()),
        show_blob=_blobs(main_tf, render_versions_tf()),
        module_source_dir=_MODULE,
        runner=RecordingRunner(),
        checkov=FakeCheckov(),
    )
    assert evidence is not None
    assert evidence.terminal_outcome is TerminalOutcome.UNSUPPORTED


def _handoff(tmp_path: Path) -> Path:
    main_tf, versions_tf = _rendered_sqs()
    output = tmp_path / "handoff"
    result = prepare(
        pr_number=29,
        proposal_sha=_PROPOSAL,
        purpose="profile",
        executor_sha=_EXECUTOR,
        output_dir=output,
        reader=Reader(_head()),
        show_blob=_blobs(main_tf, versions_tf),
        module_source_dir=_MODULE,
        runner=RecordingRunner(),
        checkov=FakeCheckov(),
    )
    assert result is None
    return output


def _credentials():
    return {
        "AWS_ACCESS_KEY_ID": "ASIAEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "AWS_SESSION_TOKEN": "session",
    }


def _identity() -> tuple[str, str]:
    return AWS_ACCOUNT_ID, _ASSUMED


class PlanRunner:
    def __init__(self, shown: dict, *, error: TerraformCommandError | None = None) -> None:
        self.shown = shown
        self.error = error
        self.workspaces: list[Path] = []

    def plan(self, workspace, plan_filename="tfplan", *, env_overrides=None):
        self.workspaces.append(Path(workspace))
        v3_plan_env(env_overrides or {})
        target = Path(workspace) / plan_filename
        target.write_text("binary-plan", encoding="utf-8")
        if self.error is not None:
            raise self.error
        return CommandResult(
            command=("terraform", "plan"),
            returncode=0,
            stdout="",
            stderr="",
            duration_seconds=0.0,
        )

    def show_json(self, workspace, plan_filename="tfplan", *, env_overrides=None):
        return self.shown


def test_verify_handoff_command_does_not_require_aws_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    root = _handoff(tmp_path)
    evidence = tmp_path / "evidence.json"
    assert (
        verify_handoff_command(
            handoff=root,
            executor_sha=_EXECUTOR,
            evidence_path=evidence,
            purpose="profile",
            module_source_dir=_MODULE,
        )
        == 0
    )
    assert not evidence.exists()
    main_tf = root / "workspace" / "main.tf"
    main_tf.write_text(main_tf.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code = verify_handoff_command(
        handoff=root,
        executor_sha=_EXECUTOR,
        evidence_path=evidence,
        purpose="profile",
        module_source_dir=_MODULE,
    )
    assert code != 0
    assert "AWS_ACCESS_KEY_ID" not in evidence.read_text(encoding="utf-8")


def test_plan_refuses_bad_handoff_before_assume(tmp_path):
    root = _handoff(tmp_path)
    main_tf = root / "workspace" / "main.tf"
    main_tf.write_text(main_tf.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    called = {"n": 0}

    def load_credentials():
        called["n"] += 1
        return _credentials()

    evidence = plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "evidence.json",
        purpose="profile",
        load_credentials=load_credentials,
        identity_lookup=_identity,
        runner=PlanRunner({"resource_changes": []}),
    )
    assert called["n"] == 0
    assert evidence.terminal_outcome is TerminalOutcome.CONFIGURATION_ERROR


def test_plan_uses_reconstructed_workspace(tmp_path):
    root = _handoff(tmp_path)
    shown = {
        "resource_changes": [
            {
                "address": "module.queue.aws_sqs_queue.this",
                "change": {"actions": ["create"]},
            }
        ]
    }
    runner = PlanRunner(shown)
    evidence = plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "evidence.json",
        purpose="acceptance",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=runner,
    )
    assert runner.workspaces == [root / "workspace"]
    assert evidence.terminal_outcome is TerminalOutcome.PASS
    assert "skip_credentials_validation" not in (root / "workspace" / "main.tf").read_text(
        encoding="utf-8"
    )


def test_destructive_plan_is_plan_blocked(tmp_path):
    root = _handoff(tmp_path)
    shown = {
        "resource_changes": [
            {
                "address": "module.queue.aws_sqs_queue.this",
                "change": {"actions": ["delete"], "before": {"name": "order-events"}},
            }
        ]
    }
    evidence = plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "evidence.json",
        purpose="acceptance",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=PlanRunner(shown),
    )
    assert evidence.terminal_outcome is TerminalOutcome.PLAN_BLOCKED
    text = evidence_to_json(evidence)
    assert '"before"' not in text


def test_access_denied_is_authorization_error(tmp_path):
    root = _handoff(tmp_path)
    denied = TerraformCommandError(
        CommandResult(
            command=("terraform", "plan"),
            returncode=1,
            stdout="",
            stderr=(
                "Error: reading SQS Queue: operation error SQS: GetQueueUrl, "
                "https response error StatusCode: 403, RequestID: abc, "
                "api error AccessDenied: User: arn:aws:sts::891377250201:assumed-role/"
                "IaCPlanRole/session is not authorized to perform: sqs:GetQueueUrl "
                "on resource: arn:aws:sqs:us-east-1:891377250201:order-events"
            ),
            duration_seconds=0.0,
        )
    )
    evidence = plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "denied.json",
        purpose="profile",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=PlanRunner({"resource_changes": []}, error=denied),
    )
    assert evidence.terminal_outcome is TerminalOutcome.AUTHORIZATION_ERROR
    assert evidence.profile_candidate_action == "sqs:GetQueueUrl"

    bare = TerraformCommandError(
        CommandResult(
            command=("terraform", "plan"),
            returncode=1,
            stdout="",
            stderr="Error: AccessDenied",
            duration_seconds=0.0,
        )
    )
    root2 = _handoff(tmp_path / "second")
    other = plan_validated(
        handoff_dir=root2,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "bare.json",
        purpose="profile",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=PlanRunner({"resource_changes": []}, error=bare),
    )
    assert other.terminal_outcome is TerminalOutcome.AUTHORIZATION_ERROR
    assert other.profile_candidate_action is None


def test_plan_deletes_tfplan_and_show_json(tmp_path):
    root = _handoff(tmp_path)
    shown = {
        "resource_changes": [
            {
                "address": "module.queue.aws_sqs_queue.this",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"name": "SENSITIVE-BEFORE-VALUE"},
                },
            }
        ]
    }
    evidence_path = tmp_path / "evidence.json"
    plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=evidence_path,
        purpose="acceptance",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=PlanRunner(shown),
    )
    assert not (root / "workspace" / "tfplan").exists()
    text = evidence_path.read_text(encoding="utf-8")
    assert "SENSITIVE-BEFORE-VALUE" not in text
    assert "binary-plan" not in text


def test_mutating_prefix_is_not_classified(tmp_path):
    """An action whose name starts with Create stays AUTHORIZATION_ERROR."""
    root = _handoff(tmp_path)
    denied = TerraformCommandError(
        CommandResult(
            command=("terraform", "plan"),
            returncode=1,
            stdout="",
            stderr="api error AccessDenied: not authorized to perform: sqs:CreateQueue",
            duration_seconds=0.0,
        )
    )
    evidence = plan_validated(
        handoff_dir=root,
        executor_sha=_EXECUTOR,
        module_source_dir=_MODULE,
        evidence_path=tmp_path / "evidence.json",
        purpose="profile",
        load_credentials=_credentials,
        identity_lookup=_identity,
        runner=PlanRunner({"resource_changes": []}, error=denied),
    )
    assert evidence.terminal_outcome is TerminalOutcome.AUTHORIZATION_ERROR
    assert evidence.profile_candidate_action == "sqs:CreateQueue"
    assert evidence.terminal_outcome is not TerminalOutcome.UNSUPPORTED

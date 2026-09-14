"""Integration proof: the real `GitHubSourceControl` adapter wired into
the real LangGraph workflow through `SourceControlPort`, with real
SQLite checkpointing (Batch 14).

This complements two other test suites rather than duplicating them:

- tests/unit/git/test_github.py proves the adapter's own HTTP request
  sequence, payloads, and error mapping in isolation.
- tests/integration/test_sqs_workflow_hitl.py proves the full pipeline
  against *real* Terraform and Checkov binaries, using a test-only
  `FakeSourceControl` (no real GitHub involved at all).

This file proves the missing link: does the concrete
`GitHubSourceControl` class — not a test double — actually satisfy
`SourceControlPort` and work correctly when the graph calls it, end to
end through a real interrupt/resume/checkpoint cycle? Terraform and
Checkov are fakes here (this is not about proving their real behavior
again), and GitHub's HTTP is a fake transport (a hard Batch 14 rule:
zero real network access, zero contact with api.github.com).
"""

from __future__ import annotations

import json
from pathlib import Path

from langgraph.types import Command

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.source_control import GitCommitIdentity, PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.git.github import GitHubRepository, GitHubSourceControl, HttpResponse, HttpTransport
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult

_REPO = GitHubRepository(owner="example-user", name="iac-agent-platform")
_TOKEN = "fake-test-token-not-real"  # noqa: S105 - deliberately fake
_COMMIT_IDENTITY = GitCommitIdentity(name="Example Bot", email="example-bot@example.invalid")

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
            files={"main.tf": "# generated main\n", "versions.tf": "# generated versions\n"}
        )


class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        return CommandResult(
            command=("terraform", "fmt"), returncode=0, stdout="", stderr="", duration_seconds=0.0
        )

    def init(self, workspace, **kwargs):
        return CommandResult(
            command=("terraform", "init"), returncode=0, stdout="", stderr="", duration_seconds=0.0
        )

    def validate(self, workspace, **kwargs):
        return CommandResult(
            command=("terraform", "validate"),
            returncode=0,
            stdout="",
            stderr="",
            duration_seconds=0.0,
        )

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        return CommandResult(
            command=("terraform", "plan"), returncode=0, stdout="", stderr="", duration_seconds=0.0
        )

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return _PLAN_JSON


class FakeCheckovAdapter:
    def scan(self, workspace):
        return CheckovScanResult(
            findings=(),
            passed_checks=5,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="3.3.13",
        )


class QueueGitHubTransport(HttpTransport):
    """A fake `HttpTransport` returning canned GitHub API responses in
    call order — no real HTTP, no DNS, no contact with api.github.com."""

    def __init__(self, responses: list[HttpResponse]):
        self.calls: list[dict] = []
        self._responses = list(responses)

    def request(self, *, method, url, headers, json_body=None):
        self.calls.append({"method": method, "url": url, "json_body": json_body})
        return self._responses.pop(0)


def _json_response(status: int, payload: object) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(payload).encode("utf-8"))


def _fake_github_responses(branch_name: str) -> list[HttpResponse]:
    return [
        _json_response(404, {"message": "Not Found"}),  # branch does not exist yet
        _json_response(200, {"object": {"sha": "base-commit-sha"}}),  # base ref
        _json_response(200, {"tree": {"sha": "base-tree-sha"}}),  # base commit -> tree
        _json_response(201, {"sha": "blob-sha-main"}),  # main.tf blob
        _json_response(201, {"sha": "blob-sha-versions"}),  # versions.tf blob
        _json_response(201, {"sha": "new-tree-sha"}),  # tree
        _json_response(201, {"sha": "new-commit-sha"}),  # commit
        _json_response(201, {"ref": f"refs/heads/{branch_name}"}),  # branch ref
        _json_response(201, {"number": 99, "html_url": "https://example.invalid/pull/99"}),  # PR
    ]


def _build_graph(workspace_root: Path, checkpointer, source_control_port):
    return build_sqs_workflow(
        renderer=FakeRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=source_control_port,
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_real_github_adapter_publishes_approved_change_through_the_graph(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    request_id = "req-source-control-001"
    branch_name = f"iac-agent/{request_id}"
    config = workflow_config(request_id)

    transport = QueueGitHubTransport(_fake_github_responses(branch_name))
    source_control = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_graph(workspace_root, saver, source_control)
        first_result = graph.invoke(
            {"request_id": request_id, "resource_spec": SQSResourceSpec(name="order-events")},
            config,
        )
        assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL

        resumed_result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert resumed_result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert resumed_result["current_stage"] is WorkflowStage.COMPLETE

    pull_request = resumed_result["pull_request"]
    assert pull_request == PullRequestResult(
        number=99,
        url="https://example.invalid/pull/99",
        branch=branch_name,
        base_branch="main",
    )

    # The adapter never called anything but the fake transport, and
    # every call was scoped to the example repository.
    for call in transport.calls:
        assert call["url"].startswith(
            "https://api.github.com/repos/example-user/iac-agent-platform"
        )
    assert transport._responses == []  # every queued response was consumed exactly once

    # Reconstruct with a brand-new saver/graph to prove PullRequestResult
    # round-trips through SQLite as its own typed domain object, not a
    # plain dict, under the existing safe serializer allowlist.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_graph(workspace_root, saver2, source_control)
        recovered = graph2.get_state(config).values

    assert isinstance(recovered["pull_request"], PullRequestResult)
    assert recovered["pull_request"] == pull_request
    assert recovered["workflow_status"] is WorkflowStatus.PR_CREATED

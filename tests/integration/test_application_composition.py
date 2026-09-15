"""Integration proof: the application composition root wires the real
Phase 1 adapters together correctly, and its SQLite lifecycle closes
cleanly (Batch 15).

Terraform and Checkov are real here (skipped if unavailable) — GitHub
is a fake `HttpTransport` injected through the same composition path
production code uses (`open_application(..., github_transport=...)`),
so this proves the real `GitHubSourceControl` is actually the adapter
wired in, without any real network access.
"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager

import pytest
from pydantic import SecretStr

import iac_agent.app.composition as composition_module
from iac_agent.app.composition import open_application
from iac_agent.app.config import ApplicationConfig, load_application_config_from_env
from iac_agent.app.service import IacApplication, Phase1Application
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.git.github import HttpResponse, HttpTransport
from iac_agent.persistence.checkpoints import (
    open_sqlite_checkpointer as real_open_sqlite_checkpointer,
)
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]

# Note (Batch 16.5): unlike the other real-tool tests in this
# directory, these two do NOT use `terraform_test_env` /
# `TF_PLUGIN_CACHE_DIR` — `open_application` (the real composition
# root) constructs its own `TerraformRunner()` internally with no
# test-injection seam for its environment, and adding one purely to
# satisfy a test would be a production-code change this batch is
# explicitly scoped to avoid. These two therefore still download their
# own provider binary copy each run.

_FAKE_TOKEN = SecretStr("fake-test-token-not-real")


class QueueGitHubTransport(HttpTransport):
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
        _json_response(404, {"message": "Not Found"}),
        _json_response(200, {"object": {"sha": "base-commit-sha"}}),
        _json_response(200, {"tree": {"sha": "base-tree-sha"}}),
        _json_response(201, {"sha": "blob-sha-main"}),
        _json_response(201, {"sha": "blob-sha-versions"}),
        _json_response(201, {"sha": "new-tree-sha"}),
        _json_response(201, {"sha": "new-commit-sha"}),
        _json_response(201, {"ref": f"refs/heads/{branch_name}"}),
        _json_response(201, {"number": 123, "html_url": "https://example.invalid/pull/123"}),
    ]


def _config(tmp_path) -> ApplicationConfig:
    env = {
        "IAC_AGENT_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
        "IAC_AGENT_STATE_DB": str(tmp_path / "state.db"),
        "GITHUB_OWNER": "example-user",
        "GITHUB_REPOSITORY": "iac-agent-platform",
        "GITHUB_BASE_BRANCH": "main",
        "GITHUB_COMMIT_AUTHOR_NAME": "Example Bot",
        "GITHUB_COMMIT_AUTHOR_EMAIL": "example-bot@example.invalid",
    }
    return load_application_config_from_env(env)


def test_composition_constructs_real_adapters_and_publishes_via_fake_transport(tmp_path):
    request_id = "req-composition-001"
    branch_name = f"iac-agent/{request_id}"
    transport = QueueGitHubTransport(_fake_github_responses(branch_name))

    config = _config(tmp_path)

    with open_application(
        config, github_token=_FAKE_TOKEN, github_transport=transport
    ) as application:
        app = Phase1Application.from_application(application)

        spec = SQSResourceSpec(name="order-events", dlq=DlqSpec(enabled=True, max_receive_count=5))
        submit_view = app.submit(request_id=request_id, spec=spec)
        assert submit_view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
        assert submit_view.current_stage is WorkflowStage.APPROVAL
        # Real Terraform/Checkov actually ran (fakes never produce a
        # populated plan_summary with real resource addresses).
        assert submit_view.plan_summary.add_count == 2

        resume_view = app.resume(request_id, ApprovalDecision.APPROVE)

    assert resume_view.workflow_status is WorkflowStatus.PR_CREATED
    assert resume_view.pull_request.number == 123
    assert resume_view.pull_request.branch == branch_name
    assert len(transport.calls) == 9
    for call in transport.calls:
        assert call["url"].startswith(
            "https://api.github.com/repos/example-user/iac-agent-platform"
        )


def test_composition_request_works_through_the_existing_application_root(tmp_path):
    """Batch 19: `open_application`'s composition root builds its graph
    via `build_sqs_workflow` -> `build_iac_workflow` exactly as before —
    zero changes were needed here for a `ServerlessWorkerSpec` request
    to work, because `build_iac_workflow`'s default `trusted_module_dirs`
    already registers SQS/Lambda/DynamoDB and its `serverless_worker_
    renderer` parameter defaults to a real `ServerlessWorkerTerraformRenderer()`
    when the caller (here, `open_application`) doesn't pass one. This
    proves "prefer one shared build path" concretely rather than merely
    asserting it: no second, composition-specific application stack
    exists or was needed.
    """
    request_id = "req-composition-worker-001"
    branch_name = f"iac-agent/{request_id}"
    transport = QueueGitHubTransport(_fake_github_responses(branch_name))

    config = _config(tmp_path)

    with open_application(
        config, github_token=_FAKE_TOKEN, github_transport=transport
    ) as application:
        app = IacApplication.from_application(application)

        spec = ServerlessWorkerSpec(
            name="orders-worker",
            queue=SQSResourceSpec(name="orders-queue"),
            function=LambdaResourceSpec(
                name="orders-processor", handler="app.handler", reserved_concurrency=5
            ),
            table=DynamoDBResourceSpec(
                name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
            ),
        )
        submit_view = app.submit(request_id=request_id, spec=spec)
        assert submit_view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
        assert submit_view.current_stage is WorkflowStage.APPROVAL
        # Real Terraform/Checkov actually ran against the real
        # composition (ten resources — see
        # tests/integration/test_serverless_worker_renderer_terraform.py).
        assert submit_view.plan_summary.add_count == 10
        assert submit_view.security_status == "pass"

        resume_view = app.resume(request_id, ApprovalDecision.APPROVE)

    assert resume_view.workflow_status is WorkflowStatus.PR_CREATED
    assert resume_view.pull_request.number == 123
    assert resume_view.pull_request.branch == branch_name


def test_composition_lifecycle_closes_sqlite_connection(tmp_path, monkeypatch):
    captured = {}

    @contextmanager
    def wrapped(db_path):
        with real_open_sqlite_checkpointer(db_path) as saver:
            captured["conn"] = saver.conn
            yield saver

    monkeypatch.setattr(composition_module, "open_sqlite_checkpointer", wrapped)

    config = _config(tmp_path)
    with open_application(
        config, github_token=_FAKE_TOKEN, github_transport=QueueGitHubTransport([])
    ):
        assert "conn" in captured

    with pytest.raises(Exception):  # noqa: B017 - sqlite3.ProgrammingError on a closed connection
        captured["conn"].execute("select 1")

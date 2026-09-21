"""Batch 24, Task 12 (GATE B): real Terraform + Checkov CLI preflight
through the real `open_intent_application` composition, with a fake
`IntentInterpreterPort` (never a real OpenAI call) and a fake GitHub
`HttpTransport` (never a real network call). Skipped if terraform/checkov
are not on PATH — mirrors `tests/integration/test_application_composition.py`
exactly, including its per-file fake duplication.
"""

from __future__ import annotations

import io
import json
import shutil

import pytest
from pydantic import SecretStr

from iac_agent.app.composition import open_intent_application
from iac_agent.app.config import ApplicationConfig, load_application_config_from_env
from iac_agent.cli.main import main
from iac_agent.git.github import HttpResponse, HttpTransport
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import parse_intent_payload

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]

_FAKE_TOKEN = SecretStr("fake-test-token-not-real")

_WORKER_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "worker",
    "interaction_pattern": "asynchronous",
    "capabilities": ["queue_processing", "persistence"],
}

_WORKER_PROMPT = (
    "Build an asynchronous worker that reads messages from a queue, "
    "processes them, and saves the result."
)


class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        return parse_intent_payload(self._payload)


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


def test_cli_worker_propose_and_resume_against_real_terraform_and_checkov(tmp_path):
    request_id = "req-cli-worker-001"
    branch_name = f"iac-agent/{request_id}"
    transport = QueueGitHubTransport(_fake_github_responses(branch_name))
    config = _config(tmp_path)
    interpreter = FakeIntentInterpreter(payload=_WORKER_PAYLOAD)

    with open_intent_application(
        config, github_token=_FAKE_TOKEN, interpreter=interpreter, github_transport=transport
    ) as holder:
        propose_stdout = io.StringIO()
        exit_code = main(
            ["propose", _WORKER_PROMPT, "--request-id", request_id],
            holder=holder,
            stdin=io.StringIO(""),
            stdout=propose_stdout,
            stderr=io.StringIO(),
            isatty=False,
        )
        propose_output = propose_stdout.getvalue()
        assert exit_code == 0
        assert "outcome: awaiting_approval" in propose_output
        # Real Checkov ran against a resolver-built spec, which omits
        # reserved_concurrency (design spec §1.5/§11.1) — WARN, not
        # PASS or BLOCK, and WARN still reaches approval.
        assert "security: warn" in propose_output
        assert "plan: +10 / ~0 / -0" in propose_output

        resume_stdout = io.StringIO()
        resume_exit_code = main(
            ["resume", request_id, "--approve"],
            holder=holder,
            stdout=resume_stdout,
            stderr=io.StringIO(),
        )

    resume_output = resume_stdout.getvalue()
    assert resume_exit_code == 0
    assert "outcome: pr_created" in resume_output
    assert "pull_request_number: 123" in resume_output
    assert len(transport.calls) == 9

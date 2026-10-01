"""Fresh-process HTTP proof. Process A checkpoints; process B resumes.

The second process opens the same SQLite file with a new checkpointer,
a new graph, and a new FastAPI app. It does not reuse process A's
objects, and it does not call GitHub.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import create_app
from iac_agent.app.capabilities import (
    SOURCE_CONTROL_ABSENT_MESSAGE,
    CapabilityPresence,
    RuntimeCapabilities,
)
from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import parse_intent_payload
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.persistence.request_index import open_request_index
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.security.checkov import CheckovScanResult

_REQUEST_ID = "req-fresh"
_PROMPT = "build a worker that processes a queue and stores results"
_PR_URL = "https://example.invalid/pull/7"
_WORKER_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "worker",
    "interaction_pattern": "asynchronous",
    "capabilities": ["queue_processing", "persistence"],
}
_PLAN_JSON = {
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
    ]
}
_DENIED = (
    "module.queue.aws_sqs_queue.this",
    "example-user",
    "iac-agent-platform",
    "example-bot@example.invalid",
    "iac-agent/req-fresh",
    "base_branch",
    'resource "aws_sqs_queue"',
    "logical_name_hint",
)


def _ok(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload
        self.calls = 0

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        self.calls += 1
        return parse_intent_payload(self._payload)


class RaisingInterpreter:
    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        raise AssertionError("fresh process must not reinterpret the request")


class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        return _ok("terraform", "fmt")

    def init(self, workspace, **kwargs):
        return _ok("terraform", "init")

    def validate(self, workspace, **kwargs):
        return _ok("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        return _ok("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return _PLAN_JSON


class FakeCheckovAdapter:
    def scan(self, workspace, *, profile=None):
        return CheckovScanResult(
            findings=(),
            passed_checks=5,
            failed_checks=0,
            skipped_checks=0,
            scanner_version="3.3.13",
        )


class FakeSourceControl:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def publish_change(self, **kwargs):
        self.calls.append(kwargs)
        return PullRequestResult(
            number=7,
            url=_PR_URL,
            branch="iac-agent/req-fresh",
            base_branch="main",
        )


class RecordingObservability:
    def __init__(self) -> None:
        self.workflow: list = []

    def record_generation(self, event) -> None:
        return None

    def record_resolution(self, event) -> None:
        return None

    def record_workflow(self, event) -> None:
        self.workflow.append(event)

    def flush(self) -> None:
        return None


def _holder(tmp_path, saver, *, interpreter, source_control, observability, request_index):
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=source_control,
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
    application = IacApplication(
        graph,
        observability=observability,
        request_index=request_index,
    )
    service = IntentResolutionService(
        interpreter=interpreter,
        resolver=ArchitectureResolver(),
        application=application,
        observability=observability,
    )
    return IntentApplication(
        config=config,
        intent_service=service,
        application=application,
        capabilities=RuntimeCapabilities(
            intent_interpretation=CapabilityPresence.CONFIGURED,
            source_control_publishing=CapabilityPresence.CONFIGURED,
        ),
    )


def _checkpoint_threads(db_path) -> set[str]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute("select distinct thread_id from checkpoints").fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def _request_index_rows(db_path) -> tuple[list[str], list[tuple[str, str]]]:
    connection = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in connection.execute("pragma table_info(request_index)")]
        rows = connection.execute(
            "select request_id, created_at from request_index"
        ).fetchall()
    finally:
        connection.close()
    return columns, [(str(row[0]), str(row[1])) for row in rows]


def _assert_public(body: str, workspace: str) -> None:
    for needle in _DENIED:
        assert needle not in body
    assert workspace not in body
    assert "pending" not in body


def test_fresh_process_reads_and_approves_the_same_sqlite_checkpoint(tmp_path):
    names = FakeSourceControl.publish_change.__code__.co_names
    assert "urlopen" not in names
    assert "httpx" not in names
    assert "GitHubSourceControl" not in names

    db_path = tmp_path / "state.db"
    source_a = FakeSourceControl()
    observability_a = RecordingObservability()
    interpreter_a = FakeIntentInterpreter(payload=_WORKER_PAYLOAD)

    with open_sqlite_checkpointer(db_path) as saver_a:
        with open_request_index(db_path) as index_a:
            holder_a = _holder(
                tmp_path,
                saver_a,
                interpreter=interpreter_a,
                source_control=source_a,
                observability=observability_a,
                request_index=index_a,
            )
            index_a_id = id(index_a)
            graph_a = holder_a.application._graph
            graph_a_id = id(graph_a)
            saver_a_id = id(saver_a)
            connection_a = saver_a.conn
            with TestClient(
                create_app(holder_a, operator_secret=SecretStr("test-operator-secret"))
            ) as client_a:
                client_a.headers["Authorization"] = "Bearer test-operator-secret"
                created = client_a.post(
                    "/api/v1/requests",
                    json={
                        "natural_language_request": _PROMPT,
                        "request_id": _REQUEST_ID,
                    },
                )
                listed_a = client_a.get("/api/v1/requests")
            assert created.status_code == 201
            assert created.json()["outcome"] == "awaiting_approval"
            assert listed_a.status_code == 200
            listed_a_row = listed_a.json()["requests"][0]
            assert listed_a_row["request_id"] == _REQUEST_ID
            assert listed_a_row["workflow_status"] == "awaiting_approval"
            created_at = listed_a_row["created_at"]
            assert isinstance(created_at, str) and created_at
            assert "module.queue.aws_sqs_queue.this" not in listed_a.text
            assert interpreter_a.calls == 1
            assert source_a.calls == []
            assert observability_a.workflow
            assert {event.request_id for event in observability_a.workflow} == {_REQUEST_ID}
            assert saver_a.get_tuple(workflow_config(_REQUEST_ID)) is not None

    assert db_path.is_file()
    assert _REQUEST_ID in _checkpoint_threads(db_path)
    index_columns, index_rows = _request_index_rows(db_path)
    assert index_columns == ["request_id", "created_at"]
    assert index_rows == [(_REQUEST_ID, created_at)]
    try:
        connection_a.execute("select 1")
    except sqlite3.ProgrammingError:
        closed = True
    else:
        closed = False
    assert closed
    del holder_a, graph_a, client_a

    source_b = FakeSourceControl()
    observability_b = RecordingObservability()
    with open_sqlite_checkpointer(db_path) as saver_b:
        assert id(saver_b) != saver_a_id
        with open_request_index(db_path) as index_b:
            assert id(index_b) != index_a_id
            holder_b = _holder(
                tmp_path,
                saver_b,
                interpreter=RaisingInterpreter(),
                source_control=source_b,
                observability=observability_b,
                request_index=index_b,
            )
            assert id(holder_b.application._graph) != graph_a_id
            assert holder_b.application._graph is not None
            with TestClient(
                create_app(holder_b, operator_secret=SecretStr("test-operator-secret"))
            ) as client_b:
                client_b.headers["Authorization"] = "Bearer test-operator-secret"
                unknown = client_b.get("/api/v1/requests/req-missing")
                assert unknown.status_code == 404
                assert unknown.json() == {
                    "error": "request_not_found",
                    "message": "Request not found.",
                }
                assert "pending" not in unknown.text
                assert "awaiting_approval" not in unknown.text
                workflows_before_get = len(observability_b.workflow)
                listed_b = client_b.get("/api/v1/requests")
                loaded = client_b.get(f"/api/v1/requests/{_REQUEST_ID}")
                assert len(observability_b.workflow) == workflows_before_get
                approved = client_b.post(
                    f"/api/v1/requests/{_REQUEST_ID}/approval",
                    json={"decision": "approve"},
                )
                spec = holder_b.application._graph.get_state(workflow_config(_REQUEST_ID)).values[
                    "resource_spec"
                ]

    assert listed_b.status_code == 200
    listed_b_row = listed_b.json()["requests"][0]
    assert listed_b_row["request_id"] == _REQUEST_ID
    assert listed_b_row["created_at"] == created_at
    assert listed_b_row["workflow_status"] == "awaiting_approval"
    assert "module.queue.aws_sqs_queue.this" not in listed_b.text

    assert loaded.status_code == 200
    loaded_body = loaded.json()
    assert loaded_body["outcome"] == "awaiting_approval"
    assert loaded_body["workflow"]["workflow_status"] == listed_b_row["workflow_status"]
    assert loaded_body["intent"] is None
    assert loaded_body["resolution"]["matched_pattern"] is None
    assert loaded_body["resolution"]["architecture"] is None
    assert loaded_body["resolution"]["components"] == []
    _assert_public(loaded.text, str(tmp_path))

    assert isinstance(spec, ServerlessWorkerSpec)
    assert isinstance(spec.queue, SQSResourceSpec)
    assert isinstance(spec.function, LambdaResourceSpec)
    assert isinstance(spec.table, DynamoDBResourceSpec)

    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["outcome"] == "pr_created"
    assert approved_body["workflow"]["pull_request"] == {"url": _PR_URL}
    _assert_public(approved.text, str(tmp_path))
    assert source_a.calls == []
    assert len(source_b.calls) == 1
    assert observability_b.workflow
    assert {event.request_id for event in observability_b.workflow} == {_REQUEST_ID}
    assert all(not hasattr(event, "trace_id") for event in observability_b.workflow)


_CAPABILITY_NAMES = (
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_COMMIT_AUTHOR_NAME",
    "GITHUB_COMMIT_AUTHOR_EMAIL",
    "GITHUB_TOKEN",
    "GITHUB_BASE_BRANCH",
    "IAC_AGENT_LLM_PROVIDER",
    "IAC_AGENT_LLM_MODEL",
    "OPENAI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def _isolated_env(monkeypatch, tmp_path) -> None:
    for name in _CAPABILITY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "test-operator-secret")
    monkeypatch.setenv("IAC_AGENT_OBSERVABILITY", "off")
    monkeypatch.setenv("GITHUB_BASE_BRANCH", "main")
    monkeypatch.setenv("IAC_AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IAC_AGENT_STATE_DB", str(tmp_path / "state.db"))


def test_second_process_serves_durable_state_without_github_or_openai(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    source_a = FakeSourceControl()
    interpreter_a = FakeIntentInterpreter(payload=_WORKER_PAYLOAD)
    with open_sqlite_checkpointer(db_path) as saver_a:
        with open_request_index(db_path) as index_a:
            holder_a = _holder(
                tmp_path,
                saver_a,
                interpreter=interpreter_a,
                source_control=source_a,
                observability=RecordingObservability(),
                request_index=index_a,
            )
            connection_a = saver_a.conn
            with TestClient(
                create_app(holder_a, operator_secret=SecretStr("test-operator-secret"))
            ) as client_a:
                client_a.headers["Authorization"] = "Bearer test-operator-secret"
                created = []
                for request_id in ("req-reject", "req-approve"):
                    response = client_a.post(
                        "/api/v1/requests",
                        json={
                            "natural_language_request": _PROMPT,
                            "request_id": request_id,
                        },
                    )
                    created.append(response)
    assert [response.status_code for response in created] == [201, 201]
    assert [response.json()["outcome"] for response in created] == [
        "awaiting_approval",
        "awaiting_approval",
    ]
    assert source_a.calls == []
    try:
        connection_a.execute("select 1")
    except sqlite3.ProgrammingError:
        closed_a = True
    else:
        closed_a = False
    assert closed_a

    _isolated_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "iac_agent.app.composition.GitHubSourceControl",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GitHubSourceControl")),
    )
    monkeypatch.setattr(
        "iac_agent.intent.adapters.openai.OpenAIIntentInterpreter",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenAIIntentInterpreter")),
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("urlopen")),
    )
    published: list[dict] = []

    from iac_agent.git.unavailable import UnavailableSourceControl

    real_publish = UnavailableSourceControl.publish_change

    def _record_publish(self, **kwargs):
        published.append(kwargs)
        return real_publish(self, **kwargs)

    monkeypatch.setattr(UnavailableSourceControl, "publish_change", _record_publish)
    app_b = create_app()
    auth = {"Authorization": "Bearer test-operator-secret"}
    with TestClient(app_b) as client_b:
        holder_b = app_b.state.holder
        connection_b = holder_b.application._graph.checkpointer.conn
        health = client_b.get("/health")
        ready = client_b.get("/ready")
        listed = client_b.get("/api/v1/requests", headers=auth)
        detail = client_b.get("/api/v1/requests/req-reject", headers=auth)
        rejected = client_b.post(
            "/api/v1/requests/req-reject/approval",
            json={"decision": "reject"},
            headers=auth,
        )
        denied = client_b.post(
            "/api/v1/requests/req-approve/approval",
            json={"decision": "approve"},
            headers=auth,
        )
        still_waiting = client_b.get("/api/v1/requests/req-approve", headers=auth)
    assert holder_b.intent_service is None
    assert holder_b.capabilities.intent_interpretation is CapabilityPresence.ABSENT
    assert holder_b.capabilities.source_control_publishing is CapabilityPresence.ABSENT
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    rows = {row["request_id"]: row["workflow_status"] for row in listed.json()["requests"]}
    assert rows["req-reject"] == "awaiting_approval"
    assert rows["req-approve"] == "awaiting_approval"
    assert detail.status_code == 200
    assert detail.json()["outcome"] == "awaiting_approval"
    assert rejected.status_code == 200
    assert rejected.json()["outcome"] == "rejected"
    assert denied.status_code == 503
    assert denied.json() == {
        "error": "capability_unavailable",
        "message": SOURCE_CONTROL_ABSENT_MESSAGE,
    }
    assert "request_id" not in denied.json()
    waiting = still_waiting.json()
    assert still_waiting.status_code == 200
    assert waiting["outcome"] == "awaiting_approval"
    assert waiting["workflow"]["approval_decision"] is None
    assert waiting["workflow"]["pull_request"] is None
    assert waiting["workflow"]["error"] is None
    rendered = listed.text + denied.text
    assert "test-operator-secret" not in rendered
    assert "test-github-token" not in rendered
    assert "test-openai-key" not in rendered
    assert published == []
    columns, index_rows = _request_index_rows(db_path)
    assert columns == ["request_id", "created_at"]
    assert {row[0] for row in index_rows} == {"req-reject", "req-approve"}
    try:
        connection_b.execute("select 1")
    except sqlite3.ProgrammingError:
        closed_b = True
    else:
        closed_b = False
    assert closed_b
    with open_sqlite_checkpointer(db_path) as saver:
        rejected_values = saver.get_tuple(workflow_config("req-reject")).checkpoint[
            "channel_values"
        ]
        waiting_values = saver.get_tuple(workflow_config("req-approve")).checkpoint[
            "channel_values"
        ]
    assert rejected_values["workflow_status"] is WorkflowStatus.REJECTED
    assert waiting_values["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert waiting_values.get("approval_decision") is None
    assert waiting_values.get("pull_request") is None
    assert waiting_values.get("error") is None

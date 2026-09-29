"""GET /api/v1/requests is a newest-page catalog beside the existing request routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from iac_agent.api.app import create_app
from iac_agent.app.service import IndexedRequest, WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import ResolvedArchitecture
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_HIDDEN = (
    'resource "aws_sqs_queue"',
    "module.queue.aws_sqs_queue.this",
    "arn:aws:sqs:us-east-1:123456789012:hidden",
    "HIDDEN_FINDING_MESSAGE",
    "HIDDEN_WORKFLOW_ERROR_MESSAGE",
    "/var/lib/iac-agent/workspaces/secret",
    "HIDDEN_CHECKPOINT_SENTINEL",
    "example-owner",
    "example-repository",
    "ghp_exampleTokenShouldNeverRender",
)


def _view(
    request_id: str,
    status: WorkflowStatus,
    *,
    name: str | None,
    security: str | None,
) -> WorkflowView:
    return WorkflowView(
        request_id=request_id,
        workflow_status=status,
        current_stage=WorkflowStage.APPROVAL,
        resource_name=name,
        security_status=security,
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=None,
    )


class _Application:
    def __init__(self) -> None:
        self.views: dict[str, WorkflowView] = {}
        self.rows: tuple[tuple[str, str], ...] = ()
        self.limits: list[int] = []
        self.resume_calls: list[tuple[str, ApprovalDecision]] = []

    def read(self, request_id: str) -> WorkflowView | None:
        return self.views.get(request_id)

    def list_requests(self, *, limit: int) -> tuple[IndexedRequest, ...]:
        self.limits.append(limit)
        found: list[IndexedRequest] = []
        for request_id, created_at in self.rows[:limit]:
            view = self.views.get(request_id)
            if view is None:
                continue
            found.append(IndexedRequest(view=view, created_at=created_at))
        return tuple(found)

    def resume(self, request_id: str, decision: ApprovalDecision) -> WorkflowView:
        self.resume_calls.append((request_id, decision))
        current = self.views[request_id]
        published = WorkflowView(
            request_id=request_id,
            workflow_status=WorkflowStatus.PR_CREATED,
            current_stage=current.current_stage,
            resource_name=current.resource_name,
            security_status=current.security_status,
            plan_summary=None,
            approval_decision=ApprovalDecision.APPROVE,
            pull_request=None,
            error=None,
        )
        self.views[request_id] = published
        return published


class _Intent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def submit(self, *, request_id: str, natural_language_request: str) -> IntentSubmissionResult:
        self.calls.append((request_id, natural_language_request))
        return IntentSubmissionResult(
            request_id=request_id,
            intent=ArchitectureIntent(
                workload_type=WorkloadType.STORAGE,
                interaction_pattern=InteractionPattern.UNSPECIFIED,
                capabilities=frozenset({Capability.OBJECT_STORAGE}),
            ),
            resolution=ResolvedArchitecture(
                request_spec=SQSResourceSpec(name="order-events"),
                matched_pattern="storage+object_storage",
            ),
            workflow_view=_view(
                request_id,
                WorkflowStatus.AWAITING_APPROVAL,
                name="order-events",
                security="pass",
            ),
        )


def _client(application: _Application, intent: _Intent | None = None) -> TestClient:
    holder = type("Holder", (), {})()
    holder.application = application
    holder.intent_service = intent if intent is not None else _Intent()
    return TestClient(create_app(holder=holder))


def test_collection_returns_newest_rows_and_valid_limits():
    application = _Application()
    application.views = {
        "req-new": _view(
            "req-new", WorkflowStatus.AWAITING_APPROVAL, name="orders", security="pass"
        ),
        "req-old": _view("req-old", WorkflowStatus.BLOCKED, name=None, security=None),
    }
    application.rows = (
        ("req-new", "2026-09-29T00:00:02.000000Z"),
        ("req-missing", "2026-09-29T00:00:01.500000Z"),
        ("req-old", "2026-09-29T00:00:01.000000Z"),
    )
    client = _client(application)
    response = client.get("/api/v1/requests")
    assert response.status_code == 200
    assert application.limits == [20]
    body = response.json()
    assert [row["request_id"] for row in body["requests"]] == ["req-new", "req-old"]
    assert body["requests"][0]["workflow_status"] == "awaiting_approval"
    assert body["requests"][0]["approval_available"] is True
    assert body["requests"][0]["created_at"] == "2026-09-29T00:00:02.000000Z"
    assert body["requests"][1]["security_status"] is None
    assert body["requests"][1]["name"] is None
    assert body["requests"][1]["approval_available"] is False
    assert set(body["requests"][0]) == {
        "request_id",
        "created_at",
        "workflow_status",
        "approval_available",
        "security_status",
        "name",
    }

    limited = client.get("/api/v1/requests?limit=1")
    assert limited.status_code == 200
    assert limited.json()["requests"][0]["request_id"] == "req-new"
    assert client.get("/api/v1/requests?limit=50").status_code == 200
    assert application.limits == [20, 1, 50]


def test_invalid_limits_are_422_and_do_not_list():
    application = _Application()
    client = _client(application)
    for value in ("0", "-1", "51", "abc", "1.5"):
        response = client.get(f"/api/v1/requests?limit={value}")
        assert response.status_code == 422
        assert response.json().get("error") != "invalid_request"
    assert application.limits == []


def test_empty_collection_is_an_empty_array():
    response = _client(_Application()).get("/api/v1/requests")
    assert response.status_code == 200
    assert response.json() == {"requests": []}


def test_list_hides_checkpoint_internals():
    finding = SecurityFinding(
        policy_id="SQS_ENCRYPTION",
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.PASS,
        resource="arn:aws:sqs:us-east-1:123456789012:hidden",
        message="HIDDEN_FINDING_MESSAGE module.queue.aws_sqs_queue.this",
        source=FindingSource.PLATFORM_POLICY,
    )
    view = WorkflowView(
        request_id="req-hidden",
        workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="orders",
        security_status="pass",
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=WorkflowError(
            stage=WorkflowStage.ERROR,
            error_type="RuntimeError",
            message=(
                "HIDDEN_WORKFLOW_ERROR_MESSAGE /var/lib/iac-agent/workspaces/secret "
                "HIDDEN_CHECKPOINT_SENTINEL example-owner example-repository "
                'ghp_exampleTokenShouldNeverRender resource "aws_sqs_queue"'
            ),
        ),
        security_gate=SecurityGateResult(findings=(finding,)),
    )
    application = _Application()
    application.views = {"req-hidden": view}
    application.rows = (("req-hidden", "2026-09-29T00:00:00.000000Z"),)
    text = _client(application).get("/api/v1/requests").text
    for sentinel in _HIDDEN:
        assert sentinel not in text


def test_existing_request_routes_stay_in_place():
    application = _Application()
    intent = _Intent()
    client = _client(application, intent)
    missing = client.get("/api/v1/requests/req-missing")
    assert missing.status_code == 404
    assert missing.json()["error"] == "request_not_found"

    created = client.post(
        "/api/v1/requests",
        json={"natural_language_request": "build a bucket", "request_id": "req-001"},
    )
    assert created.status_code == 201
    assert created.json()["outcome"] == "awaiting_approval"
    assert "build a bucket" not in created.text
    assert intent.calls == [("req-001", "build a bucket")]

    application.views["req-001"] = _view(
        "req-001",
        WorkflowStatus.AWAITING_APPROVAL,
        name="order-events",
        security="pass",
    )
    detail = client.get("/api/v1/requests/req-001")
    assert detail.status_code == 200
    assert detail.json()["request_id"] == "req-001"
    assert "workflow" in detail.json()

    approved = client.post("/api/v1/requests/req-001/approval", json={"decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["workflow"]["workflow_status"] == "pr_created"
    assert application.resume_calls == [("req-001", ApprovalDecision.APPROVE)]

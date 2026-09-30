"""Operator routes reject anonymous callers before application behavior."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import create_app
from iac_agent.app.service import WorkflowView
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import ResolvedArchitecture
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_SECRET = "test-operator-secret"
_UNAUTHORIZED = {"error": "unauthenticated", "message": "Authentication is required."}


class _ListEntry:
    def __init__(self, view: WorkflowView) -> None:
        self.view = view
        self.created_at = "2026-09-29T00:00:00Z"


class _Application:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.lists: list[int] = []
        self.resumes: list[tuple[str, object]] = []
        self.stored: dict[str, WorkflowView] = {}

    def read(self, request_id: str):
        self.reads.append(request_id)
        return self.stored.get(request_id)

    def list_requests(self, limit: int):
        self.lists.append(limit)
        return [_ListEntry(view) for view in self.stored.values()]

    def resume(self, request_id: str, decision: object):
        self.resumes.append((request_id, decision))
        return self.stored[request_id]


class _Intent:
    def __init__(self) -> None:
        self.submits: list[tuple[str, str]] = []
        self.result: IntentSubmissionResult | None = None

    def submit(self, *, request_id: str, natural_language_request: str):
        self.submits.append((request_id, natural_language_request))
        if self.result is None:
            raise AssertionError("submit must not run")
        return self.result


class _Holder:
    def __init__(self) -> None:
        self.application = _Application()
        self.intent_service = _Intent()


def _client(holder: _Holder) -> TestClient:
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    return TestClient(app)


def _assert_unauthorized(response, holder: _Holder) -> None:
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED
    assert "request_id" not in response.json()
    assert _SECRET not in response.text
    assert "wrong-secret" not in response.text
    assert holder.application.reads == []
    assert holder.application.lists == []
    assert holder.application.resumes == []
    assert holder.intent_service.submits == []


def test_anonymous_operator_routes_are_401(caplog):
    holder = _Holder()
    client = _client(holder)
    caplog.set_level(logging.DEBUG)
    calls = [
        client.post("/api/v1/requests", json={"natural_language_request": "queue"}),
        client.get("/api/v1/requests"),
        client.get("/api/v1/requests/req-missing"),
        client.post("/api/v1/requests/req-missing/approval", json={"decision": "approve"}),
    ]
    for response in calls:
        _assert_unauthorized(response, holder)
    assert _SECRET not in caplog.text


def test_wrong_bearer_and_wrong_scheme_match_anonymous_401(caplog):
    holder = _Holder()
    client = _client(holder)
    caplog.set_level(logging.DEBUG)
    wrong = {"Authorization": "Bearer wrong-secret"}
    basic = {"Authorization": f"Basic {_SECRET}"}
    empty = {"Authorization": "Bearer "}
    malformed = {"Authorization": f"Bearer {_SECRET} extra"}
    for headers in (wrong, basic, empty, malformed):
        detail = client.get("/api/v1/requests/req-missing", headers=headers)
        approval = client.post(
            "/api/v1/requests/req-missing/approval",
            json={"decision": "approve"},
            headers=headers,
        )
        _assert_unauthorized(detail, holder)
        _assert_unauthorized(approval, holder)
        assert detail.json() == approval.json() == _UNAUTHORIZED
    assert _SECRET not in caplog.text
    assert "wrong-secret" not in caplog.text


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_SECRET}"}


def _view(status: WorkflowStatus = WorkflowStatus.AWAITING_APPROVAL) -> WorkflowView:
    return WorkflowView(
        request_id="req-001",
        workflow_status=status,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="order-events",
        security_status="pass",
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=None,
        security_gate=None,
    )


def _submission() -> IntentSubmissionResult:
    return IntentSubmissionResult(
        request_id="req-001",
        intent=ArchitectureIntent(
            workload_type=WorkloadType.STORAGE,
            interaction_pattern=InteractionPattern.UNSPECIFIED,
            capabilities=frozenset({Capability.OBJECT_STORAGE}),
        ),
        resolution=ResolvedArchitecture(
            request_spec=SQSResourceSpec(name="order-events"),
            matched_pattern="storage+object_storage",
        ),
        workflow_view=_view(),
    )


def test_valid_bearer_preserves_lookup_validation_and_application_behavior():
    holder = _Holder()
    holder.intent_service.result = _submission()
    holder.application.stored = {"req-001": _view()}
    client = _client(holder)
    created = client.post(
        "/api/v1/requests",
        json={"natural_language_request": "queue"},
        headers=_auth(),
    )
    assert created.status_code == 201
    assert created.json()["request_id"] == "req-001"
    assert _SECRET not in created.text
    listed = client.get("/api/v1/requests", headers=_auth())
    assert listed.status_code == 200
    assert listed.json()["requests"][0]["request_id"] == "req-001"
    missing = client.get("/api/v1/requests/req-missing", headers=_auth())
    assert missing.status_code == 404
    assert missing.json()["error"] == "request_not_found"
    invalid = client.get("/api/v1/requests/%2E%2E", headers=_auth())
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "invalid_request_id"
    assert "req-missing" in holder.application.reads
    assert ".." not in holder.application.reads
    limited = client.get("/api/v1/requests", params={"limit": 0}, headers=_auth())
    assert limited.status_code == 422
    detail = client.get("/api/v1/requests/req-001", headers=_auth())
    assert detail.status_code == 200
    assert detail.json()["request_id"] == "req-001"
    approval = client.post(
        "/api/v1/requests/req-001/approval",
        json={"decision": "approve"},
        headers=_auth(),
    )
    assert approval.status_code == 200
    assert holder.application.resumes

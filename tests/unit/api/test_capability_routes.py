"""Operation-boundary capability gates. No provider calls."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import create_app
from iac_agent.app.capabilities import (
    INTENT_ABSENT_MESSAGE,
    SOURCE_CONTROL_ABSENT_MESSAGE,
    CapabilityPresence,
    RuntimeCapabilities,
)
from iac_agent.app.service import WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus

_SECRET = "test-operator-secret"
_OPENAI_VALUE = "test-openai-key-not-used"


class _Application:
    def __init__(self) -> None:
        self.stored: dict[str, object] = {}
        self.checkpoints: dict[str, object] = {}
        self.index: dict[str, object] = {}
        self.reads: list[str] = []
        self.submits: list[str] = []
        self.invokes: list[str] = []

    def read(self, request_id: str):
        self.reads.append(request_id)
        return self.stored.get(request_id)

    def submit(self, request_id: str):
        self.submits.append(request_id)
        raise AssertionError("application.submit must not run")

    def invoke(self, request_id: str):
        self.invokes.append(request_id)
        raise AssertionError("graph.invoke must not run")


class _Intent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.interprets: list[str] = []

    def interpret(self, text: str):
        self.interprets.append(text)
        raise AssertionError("interpret must not run")

    def submit(self, *, request_id: str, natural_language_request: str):
        self.calls.append((request_id, natural_language_request))
        raise AssertionError("submit must not run")


class _Holder:
    def __init__(self) -> None:
        self.application = _Application()
        self.intent_service = _Intent()
        self.capabilities = RuntimeCapabilities(
            intent_interpretation=CapabilityPresence.ABSENT,
            source_control_publishing=CapabilityPresence.ABSENT,
        )


def _client(holder: _Holder) -> TestClient:
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {_SECRET}"
    return client


def _post(client: TestClient, request_id: str):
    return client.post(
        "/api/v1/requests",
        json={"natural_language_request": "build a queue", "request_id": request_id},
    )


def test_new_request_without_an_interpreter_does_not_submit():
    holder = _Holder()
    response = _post(_client(holder), "req-new")
    assert response.status_code == 503
    assert response.json() == {
        "error": "capability_unavailable",
        "message": INTENT_ABSENT_MESSAGE,
    }
    assert "request_id" not in response.json()
    assert _SECRET not in response.text
    assert _OPENAI_VALUE not in response.text
    assert holder.intent_service.calls == []
    assert holder.intent_service.interprets == []
    assert holder.application.submits == []
    assert holder.application.invokes == []
    assert "req-new" not in holder.application.checkpoints
    assert "req-new" not in holder.application.index
    assert "req-new" not in holder.application.stored


def test_existing_request_still_conflicts_without_an_interpreter():
    holder = _Holder()
    holder.application.stored["req-old"] = object()
    response = _post(_client(holder), "req-old")
    assert response.status_code == 409
    assert response.json()["error"] == "request_exists"
    assert holder.intent_service.calls == []
    assert holder.intent_service.interprets == []


def test_unauthenticated_submit_is_401_before_the_capability_check():
    holder = _Holder()
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    response = TestClient(app).post(
        "/api/v1/requests",
        json={"natural_language_request": "build a queue", "request_id": "req-new"},
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthenticated",
        "message": "Authentication is required.",
    }
    assert holder.application.reads == []
    assert holder.intent_service.calls == []


def _view(
    request_id: str,
    status: WorkflowStatus,
    decision: ApprovalDecision | None = None,
    pull_request: PullRequestResult | None = None,
) -> WorkflowView:
    return WorkflowView(
        request_id=request_id,
        workflow_status=status,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="order-events",
        security_status="pass",
        plan_summary=None,
        approval_decision=decision,
        pull_request=pull_request,
        error=None,
        security_gate=None,
    )


class _Publisher:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def publish_change(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("publish_change must not run")


class _ApprovalApplication:
    def __init__(self) -> None:
        self.views = {
            "req-wait": _view("req-wait", WorkflowStatus.AWAITING_APPROVAL),
            "req-published": _view(
                "req-published",
                WorkflowStatus.PR_CREATED,
                ApprovalDecision.APPROVE,
                PullRequestResult(
                    number=1,
                    url="https://example.invalid/pull/1",
                    branch="iac-agent/req-published",
                    base_branch="main",
                ),
            ),
            "req-rejected": _view(
                "req-rejected",
                WorkflowStatus.REJECTED,
                ApprovalDecision.REJECT,
            ),
        }
        self.reads: list[str] = []
        self.resume_calls: list[tuple[str, ApprovalDecision]] = []
        self.block_approve = True
        self.publisher = _Publisher()

    def read(self, request_id: str):
        self.reads.append(request_id)
        return self.views.get(request_id)

    def resume(self, request_id: str, decision: ApprovalDecision):
        self.resume_calls.append((request_id, decision))
        if decision is ApprovalDecision.APPROVE and self.block_approve:
            raise AssertionError("resume must not run")
        if decision is ApprovalDecision.REJECT:
            view = _view(request_id, WorkflowStatus.REJECTED, ApprovalDecision.REJECT)
            self.views[request_id] = view
            return view
        view = _view(
            request_id,
            WorkflowStatus.PR_CREATED,
            ApprovalDecision.APPROVE,
            PullRequestResult(
                number=7,
                url="https://example.invalid/pull/7",
                branch=f"iac-agent/{request_id}",
                base_branch="main",
            ),
        )
        self.views[request_id] = view
        return view


class _ApprovalHolder:
    def __init__(self) -> None:
        self.application = _ApprovalApplication()
        self.intent_service = None
        self.source_control = self.application.publisher
        self.capabilities = RuntimeCapabilities(
            intent_interpretation=CapabilityPresence.ABSENT,
            source_control_publishing=CapabilityPresence.ABSENT,
        )


def _approval_client(holder: _ApprovalHolder, *, authenticate: bool = True) -> TestClient:
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    client = TestClient(app)
    if authenticate:
        client.headers["Authorization"] = f"Bearer {_SECRET}"
    return client


def _decide(client: TestClient, request_id: str, decision: str):
    return client.post(
        f"/api/v1/requests/{request_id}/approval",
        json={"decision": decision},
    )


def test_approval_without_source_control_does_not_resume():
    holder = _ApprovalHolder()
    client = _approval_client(holder)
    response = _decide(client, "req-wait", "approve")
    assert response.status_code == 503
    assert response.json() == {
        "error": "capability_unavailable",
        "message": SOURCE_CONTROL_ABSENT_MESSAGE,
    }
    assert "request_id" not in response.json()
    assert _SECRET not in response.text
    assert "test-github-token-not-used" not in response.text
    assert holder.application.resume_calls == []
    assert holder.source_control.calls == []
    detail = client.get("/api/v1/requests/req-wait")
    assert detail.status_code == 200
    body = detail.json()
    assert body["outcome"] == "awaiting_approval"
    assert body["workflow"]["workflow_status"] == "awaiting_approval"
    assert body["workflow"]["approval_decision"] is None
    assert body["workflow"]["pull_request"] is None
    assert body["workflow"]["error"] is None


def test_approval_reject_without_source_control_reaches_rejected():
    holder = _ApprovalHolder()
    response = _decide(_approval_client(holder), "req-wait", "reject")
    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert holder.application.resume_calls == [("req-wait", ApprovalDecision.REJECT)]
    assert holder.source_control.calls == []


def test_approval_of_missing_request_is_not_found():
    holder = _ApprovalHolder()
    response = _decide(_approval_client(holder), "req-missing", "approve")
    assert response.status_code == 404
    assert response.json()["error"] == "request_not_found"
    assert holder.application.resume_calls == []


def test_repeated_approval_returns_current_without_source_control():
    holder = _ApprovalHolder()
    response = _decide(_approval_client(holder), "req-published", "approve")
    assert response.status_code == 200
    assert response.json()["outcome"] == "pr_created"
    assert holder.application.resume_calls == []
    assert holder.source_control.calls == []


def test_conflicting_approval_stays_409_without_source_control():
    holder = _ApprovalHolder()
    response = _decide(_approval_client(holder), "req-rejected", "approve")
    assert response.status_code == 409
    assert response.json()["error"] == "approval_conflict"
    assert holder.application.resume_calls == []
    assert holder.source_control.calls == []


def test_unauthenticated_approval_is_401_before_the_capability_check():
    holder = _ApprovalHolder()
    response = _decide(_approval_client(holder, authenticate=False), "req-wait", "approve")
    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthenticated",
        "message": "Authentication is required.",
    }
    assert holder.application.reads == []
    assert holder.application.resume_calls == []


def test_configured_source_control_approval_resumes():
    holder = _ApprovalHolder()
    holder.application.block_approve = False
    holder.capabilities = RuntimeCapabilities(
        intent_interpretation=CapabilityPresence.CONFIGURED,
        source_control_publishing=CapabilityPresence.CONFIGURED,
    )
    response = _decide(_approval_client(holder), "req-wait", "approve")
    assert response.status_code == 200
    assert response.json()["outcome"] == "pr_created"
    assert holder.application.resume_calls == [("req-wait", ApprovalDecision.APPROVE)]
    assert holder.source_control.calls == []

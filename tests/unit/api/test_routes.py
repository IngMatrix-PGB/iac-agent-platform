"""HTTP routes against an injected holder. No cloud calls."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from iac_agent.api.app import create_app
from iac_agent.app.service import WorkflowView
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderUnavailableError
from iac_agent.intent.resolver import (
    ClarificationReason,
    ClarificationRequest,
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
    UnsupportedReason,
)
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_PROMPT = "build a bucket named order-events"


class FakeApplication:
    def __init__(self) -> None:
        self.stored: dict[str, object] = {}
        self.get_state_calls: list[str] = []
        self.resume_calls: list[tuple] = []
        self.resume_result = None
        self.resume_error: BaseException | None = None

    def read(self, request_id: str):
        return self.stored.get(request_id)

    def get_state(self, request_id: str):
        self.get_state_calls.append(request_id)
        raise AssertionError("HTTP must not call get_state")

    def resume(self, request_id: str, decision):
        self.resume_calls.append((request_id, decision))
        if self.resume_result is not None:
            self.stored[request_id] = self.resume_result
        if self.resume_error is not None:
            raise self.resume_error
        if self.resume_result is None:
            raise RuntimeError("resume failed")
        return self.resume_result


class FakeIntent:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def submit(self, *, request_id: str, natural_language_request: str):
        self.calls.append((request_id, natural_language_request))
        if self.error is not None:
            raise self.error
        return self.result


class Holder:
    def __init__(self, result=None, error=None) -> None:
        self.application = FakeApplication()
        self.intent_service = FakeIntent(result=result, error=error)


def _resolved_view() -> WorkflowView:
    return WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="order-events",
        security_status="pass",
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=None,
        security_gate=None,
    )


def _resolved(request_id: str = "req-001") -> IntentSubmissionResult:
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
        workflow_view=_resolved_view(),
    )


def _client(holder: Holder, **state):
    app = create_app(holder=holder)
    for key, value in state.items():
        setattr(app.state, key, value)
    return TestClient(app)


def test_missing_natural_language_request_is_400():
    holder = Holder()
    response = _client(holder).post("/api/v1/requests", json={})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert holder.intent_service.calls == []


def test_invalid_request_id_does_not_submit():
    holder = Holder(result=_resolved())
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": _PROMPT, "request_id": "foo/bar"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request_id"
    assert holder.intent_service.calls == []


def test_existing_checkpoint_is_conflict_without_submit():
    holder = Holder(result=_resolved("req-dup"))
    holder.application.stored["req-dup"] = _resolved_view()
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": _PROMPT, "request_id": "req-dup"},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "request_exists"
    assert holder.intent_service.calls == []
    assert holder.application.get_state_calls == []


def test_clarification_is_200_without_workflow():
    holder = Holder(
        result=IntentSubmissionResult(
            request_id="req-clarify",
            intent=ArchitectureIntent(
                workload_type=WorkloadType.UNSPECIFIED,
                interaction_pattern=InteractionPattern.UNSPECIFIED,
                capabilities=frozenset(),
            ),
            resolution=ClarificationRequired(
                request=ClarificationRequest(
                    reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
                    field="workload_type",
                    allowed_values=("api", "worker", "storage"),
                )
            ),
            workflow_view=None,
        )
    )
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": "hello", "request_id": "req-clarify"},
    )
    assert response.status_code == 200
    assert response.json()["workflow"] is None
    assert response.json()["outcome"] == "clarification_required"


def test_unsupported_is_200():
    holder = Holder(
        result=IntentSubmissionResult(
            request_id="req-nope",
            intent=ArchitectureIntent(
                workload_type=WorkloadType.STORAGE,
                interaction_pattern=InteractionPattern.UNSPECIFIED,
                capabilities=frozenset({Capability.OBJECT_STORAGE}),
            ),
            resolution=UnsupportedArchitecture(
                reason=UnsupportedReason.UNSUPPORTED_CAPABILITY,
                detail="no such capability",
            ),
            workflow_view=None,
        )
    )
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": "hello", "request_id": "req-nope"},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "unsupported"


def test_resolved_request_is_201_and_hides_the_prompt():
    holder = Holder(result=_resolved("req-001"))
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": _PROMPT, "request_id": "req-001"},
    )
    assert response.status_code == 201
    assert response.headers["location"] == "/api/v1/requests/req-001"
    body = response.json()
    assert body["outcome"] == "awaiting_approval"
    assert body["resolution"]["name"] == "order-events"
    assert _PROMPT not in response.text


def test_omitted_request_id_uses_injected_clock():
    holder = Holder(result=_resolved("req-20260927T191300Z-a1b2c3d4e5f6"))
    response = _client(
        holder,
        clock=lambda: datetime(2026, 9, 27, 19, 13, tzinfo=UTC),
        entropy=lambda: "a1b2c3d4e5f6",
    ).post("/api/v1/requests", json={"natural_language_request": "queue"})
    assert response.status_code == 201
    assert holder.intent_service.calls[0][0] == "req-20260927T191300Z-a1b2c3d4e5f6"


def test_interpreter_failure_hides_exception_text():
    holder = Holder(error=IntentProviderUnavailableError("secret downstream"))
    response = _client(holder).post(
        "/api/v1/requests",
        json={"natural_language_request": "queue", "request_id": "req-down"},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "intent_provider_unavailable"
    assert response.json()["message"] == "Intent provider unavailable."
    assert "secret downstream" not in response.text


def test_unknown_valid_request_id_is_404_and_not_a_synthetic_status():
    holder = Holder()
    response = _client(holder).get("/api/v1/requests/req-missing")
    assert response.status_code == 404
    assert response.json() == {
        "error": "request_not_found",
        "message": "Request not found.",
    }
    rendered = response.text
    for forbidden in ("pending", "submitted", "awaiting_approval", "workflow_status"):
        assert forbidden not in rendered
    assert holder.application.get_state_calls == []


def test_get_existing_request_omits_intent_and_does_not_resume():
    holder = Holder()
    holder.application.stored["req-001"] = _resolved_view()
    client = _client(holder)
    first = client.get("/api/v1/requests/req-001")
    second = client.get("/api/v1/requests/req-001")
    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body["intent"] is None
    assert body["resolution"]["matched_pattern"] is None
    assert body["approval_available"] is True
    assert body["outcome"] == "awaiting_approval"
    assert holder.application.resume_calls == []
    assert holder.application.get_state_calls == []


def _terminal(status: WorkflowStatus, decision=None) -> WorkflowView:
    return WorkflowView(
        request_id="req-001",
        workflow_status=status,
        current_stage=WorkflowStage.COMPLETE,
        resource_name="order-events",
        security_status="block" if status is WorkflowStatus.BLOCKED else "pass",
        plan_summary=None,
        approval_decision=decision,
        pull_request=None,
        error=None,
    )


def test_approve_awaiting_calls_resume_once():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _resolved_view()
    holder.application.resume_result = _terminal(
        WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "pr_created"
    assert len(holder.application.resume_calls) == 1


def test_reject_awaiting_calls_resume_once():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _resolved_view()
    holder.application.resume_result = _terminal(
        WorkflowStatus.REJECTED, ApprovalDecision.REJECT
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "reject"}
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"
    assert len(holder.application.resume_calls) == 1


def test_repeated_approve_does_not_resume():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _terminal(
        WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "pr_created"
    assert holder.application.resume_calls == []


def test_repeated_reject_does_not_resume():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _terminal(
        WorkflowStatus.REJECTED, ApprovalDecision.REJECT
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "reject"}
    )
    assert response.status_code == 200
    assert holder.application.resume_calls == []


def test_approve_after_reject_is_conflict():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _terminal(
        WorkflowStatus.REJECTED, ApprovalDecision.REJECT
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "approve"}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "approval_conflict"
    assert body["request"]["outcome"] == "rejected"
    assert holder.application.resume_calls == []


def test_reject_after_approve_is_conflict():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _terminal(
        WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE
    )
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "reject"}
    )
    assert response.status_code == 409
    assert response.json()["error"] == "approval_conflict"
    assert holder.application.resume_calls == []


def test_approval_while_blocked_or_error_is_conflict():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-blocked"] = _terminal(WorkflowStatus.BLOCKED)
    blocked = _client(holder).post(
        "/api/v1/requests/req-blocked/approval", json={"decision": "approve"}
    )
    holder.application.stored["req-error"] = _terminal(
        WorkflowStatus.ERROR, ApprovalDecision.APPROVE
    )
    failed = _client(holder).post(
        "/api/v1/requests/req-error/approval", json={"decision": "approve"}
    )
    assert blocked.status_code == 409
    assert failed.status_code == 409
    assert failed.json()["request"]["outcome"] == "error"
    assert holder.application.resume_calls == []


def test_unknown_approval_is_404():
    response = _client(Holder()).post(
        "/api/v1/requests/req-missing/approval", json={"decision": "approve"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "request_not_found"


def test_malformed_approval_decision_is_400():
    holder = Holder()
    holder.application.stored["req-001"] = _resolved_view()
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "yes"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_approval"
    assert holder.application.resume_calls == []


def test_malformed_approval_request_id_is_400():
    response = _client(Holder()).post(
        "/api/v1/requests/%2E%2E/approval", json={"decision": "approve"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request_id"


def test_resume_exception_returns_durable_result_without_a_second_resume():
    from iac_agent.domain.approval import ApprovalDecision

    holder = Holder()
    holder.application.stored["req-001"] = _resolved_view()
    holder.application.resume_result = _terminal(
        WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE
    )
    holder.application.resume_error = RuntimeError("sdk down secret")
    response = _client(holder).post(
        "/api/v1/requests/req-001/approval", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "pr_created"
    assert "sdk down" not in response.text
    assert len(holder.application.resume_calls) == 1

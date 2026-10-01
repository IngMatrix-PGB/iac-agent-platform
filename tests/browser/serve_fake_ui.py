"""Localhost fake API for the operator-UI browser tests.

This process serves create_app(holder) only. It does not construct AWS,
OpenAI, GitHub, or Langfuse clients.
"""

from __future__ import annotations

import hmac
import json

import uvicorn
from pydantic import SecretStr

import iac_agent.api.routes as routes
from iac_agent.api.app import create_app
from iac_agent.app.capabilities import CapabilityPresence, RuntimeCapabilities
from iac_agent.app.service import IndexedRequest, WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import ResolvedArchitecture
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

REQUEST_ID = "req-browser"
CATALOG_ID = "req-indexed"
CATALOG_CREATED_AT = "2026-09-29T00:00:00.000000Z"
OPERATOR_SECRET = "test-operator-secret"
_CONFLICT_PROMPT = "conflict please"
_UNAUTHORIZED = b'{"error":"unauthenticated","message":"Authentication is required."}'


def _fixed_request_id(now=None, entropy=None) -> str:
    del now, entropy
    return REQUEST_ID


def _plan() -> PlanSummary:
    return PlanSummary(
        resource_changes=(),
        resources_to_add=("aws_sqs_queue.hidden_address",),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def _gate() -> SecurityGateResult:
    return SecurityGateResult(
        findings=(
            SecurityFinding(
                policy_id="SQS_ENCRYPTION",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.PASS,
                resource="arn:aws:sqs:us-east-1:123456789012:hidden",
                message="HIDDEN_FINDING_MESSAGE",
                source=FindingSource.PLATFORM_POLICY,
            ),
        )
    )


def _view(
    status: WorkflowStatus,
    decision: ApprovalDecision | None,
    pull_request: PullRequestResult | None,
) -> WorkflowView:
    return WorkflowView(
        request_id=REQUEST_ID,
        workflow_status=status,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="order-events",
        security_status="pass",
        plan_summary=_plan(),
        approval_decision=decision,
        pull_request=pull_request,
        error=None,
        security_gate=_gate(),
    )


def _catalog_view() -> WorkflowView:
    return WorkflowView(
        request_id=CATALOG_ID,
        workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="orders",
        security_status="pass",
        plan_summary=_plan(),
        approval_decision=None,
        pull_request=None,
        error=None,
        security_gate=_gate(),
    )


def _awaiting() -> WorkflowView:
    return _view(WorkflowStatus.AWAITING_APPROVAL, None, None)


def _rejected() -> WorkflowView:
    return _view(WorkflowStatus.REJECTED, ApprovalDecision.REJECT, None)


def _published() -> WorkflowView:
    return _view(
        WorkflowStatus.PR_CREATED,
        ApprovalDecision.APPROVE,
        PullRequestResult(
            number=7,
            url="https://example.invalid/pull/7",
            branch="iac-agent/req-browser",
            base_branch="main",
        ),
    )


class BrowserApplication:
    """In-memory stand-in for IacApplication.read and resume."""

    def __init__(self) -> None:
        self.phase = "empty"
        self.stored: WorkflowView | None = None

    def begin(self, prompt: str) -> None:
        self.stored = None
        self.phase = "conflict_fresh" if prompt == _CONFLICT_PROMPT else "happy_fresh"

    def mark_approval(self) -> None:
        if self.phase == "conflict_loaded":
            self.phase = "conflict_approval"

    def list_requests(self, *, limit: int) -> tuple[IndexedRequest, ...]:
        del limit
        return (IndexedRequest(view=_catalog_view(), created_at=CATALOG_CREATED_AT),)

    def read(self, request_id: str) -> WorkflowView | None:
        if request_id == CATALOG_ID:
            return _catalog_view()
        if request_id != REQUEST_ID:
            return None
        if self.phase == "conflict_fresh":
            self.phase = "conflict_loaded"
            return None
        if self.phase == "happy_fresh":
            self.phase = "happy_loaded"
            return None
        if self.phase == "conflict_loaded":
            return self.stored or _awaiting()
        if self.phase == "conflict_approval":
            return _rejected()
        if self.phase == "happy_loaded":
            return self.stored or _awaiting()
        if self.phase == "published":
            return _published()
        if self.phase == "rejected":
            return self.stored or _rejected()
        return None

    def resume(self, request_id: str, decision: ApprovalDecision) -> WorkflowView:
        del request_id
        if self.phase.startswith("conflict"):
            raise AssertionError("conflict path must not resume")
        if decision is ApprovalDecision.REJECT:
            rejected = _rejected()
            self.stored = rejected
            self.phase = "rejected"
            return rejected
        published = _published()
        self.stored = published
        self.phase = "published"
        return published


class BrowserIntent:
    def __init__(self, application: BrowserApplication) -> None:
        self.application = application

    def submit(self, *, request_id: str, natural_language_request: str) -> IntentSubmissionResult:
        del natural_language_request
        view = _awaiting()
        self.application.stored = view
        return IntentSubmissionResult(
            request_id=request_id,
            intent=ArchitectureIntent(
                workload_type=WorkloadType.WORKER,
                interaction_pattern=InteractionPattern.ASYNCHRONOUS,
                capabilities=frozenset({Capability.QUEUE_PROCESSING}),
            ),
            resolution=ResolvedArchitecture(
                request_spec=SQSResourceSpec(name="order-events"),
                matched_pattern="worker+asynchronous+queue_processing",
            ),
            workflow_view=view,
        )


class _PromptMode:
    def __init__(self, app, application: BrowserApplication) -> None:
        self.app = app
        self.application = application

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "")
        if _operator_route(method, path) and not _bearer_matches(scope):
            await _send_unauthorized(send)
            return
        if method == "POST" and path == f"/api/v1/requests/{REQUEST_ID}/approval":
            self.application.mark_approval()
            await self.app(scope, receive, send)
            return
        if method != "POST" or path != "/api/v1/requests":
            await self.app(scope, receive, send)
            return
        body = b""
        messages: list[dict] = []
        more = True
        while more:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            more = message.get("more_body", False)
        payload = {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
        text = payload.get("natural_language_request")
        if isinstance(text, str):
            self.application.begin(text)
        pending = iter(messages)

        async def replay():
            try:
                return next(pending)
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)


def _operator_route(method: str, path: str) -> bool:
    if path == "/api/v1/requests":
        return method in {"GET", "POST"}
    return path.startswith("/api/v1/requests/") and method in {"GET", "POST"}


def _bearer_matches(scope) -> bool:
    supplied = b""
    for name, value in scope.get("headers") or []:
        if name == b"authorization":
            supplied = value
            break
    expected = f"Bearer {OPERATOR_SECRET}".encode()
    return hmac.compare_digest(supplied, expected)


async def _send_unauthorized(send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_UNAUTHORIZED)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _UNAUTHORIZED})


def build_app():
    routes.generate_request_id = _fixed_request_id
    application = BrowserApplication()
    holder = type("Holder", (), {})()
    holder.application = application
    holder.intent_service = BrowserIntent(application)
    holder.capabilities = RuntimeCapabilities(
        intent_interpretation=CapabilityPresence.CONFIGURED,
        source_control_publishing=CapabilityPresence.CONFIGURED,
    )
    app = create_app(holder, operator_secret=SecretStr(OPERATOR_SECRET))
    app.add_middleware(_PromptMode, application=application)
    return app


def main() -> None:
    uvicorn.run(build_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

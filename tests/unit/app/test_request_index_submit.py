"""Submit records a checkpointed request. The index cannot change the view."""

from __future__ import annotations

import logging

import pytest

from iac_agent.app.service import IacApplication
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderUnavailableError
from iac_agent.intent.resolver import (
    ClarificationReason,
    ClarificationRequest,
    ClarificationRequired,
    UnsupportedArchitecture,
    UnsupportedReason,
)
from iac_agent.intent.service import IntentResolutionService
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.noop import NoOpObservability

_SECRET = 'resource "aws_sqs_queue" ghp_hidden_token_value {"plan": true}'


class _Snapshot:
    def __init__(self, values):
        self.created_at = "checkpoint"
        self.values = values


class _Graph:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.invoke_calls = 0

    def invoke(self, payload, config):
        self.invoke_calls += 1
        if self.fail:
            raise RuntimeError("workflow failed")
        request_id = config["configurable"]["thread_id"]
        return {"request_id": request_id, "workflow_status": WorkflowStatus.AWAITING_APPROVAL}

    def get_state(self, config):
        del config
        return _Snapshot({"workflow_status": WorkflowStatus.AWAITING_APPROVAL})


class _Index:
    def __init__(self, error: BaseException | None = None) -> None:
        self.ids: list[str] = []
        self.error = error

    def record(self, request_id: str) -> None:
        if self.error is not None:
            raise self.error
        self.ids.append(request_id)


class _Application:
    def __init__(self) -> None:
        self.submits: list[str] = []

    def submit(self, *, request_id: str, spec) -> None:
        del spec
        self.submits.append(request_id)


class _Interpreter:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error

    def interpret(self, *, natural_language_request: str, request_id: str):
        del natural_language_request, request_id
        if self.error is not None:
            raise self.error
        return ArchitectureIntent(
            workload_type=WorkloadType.UNSPECIFIED,
            interaction_pattern=InteractionPattern.UNSPECIFIED,
            capabilities=frozenset(),
        )


class _Resolver:
    def __init__(self, resolution) -> None:
        self.resolution = resolution

    def resolve(self, *, intent, request_id: str):
        del intent, request_id
        return self.resolution


def test_successful_submit_records_the_request_id_once():
    index = _Index()
    graph = _Graph()
    application = IacApplication(graph, request_index=index)
    view = application.submit(request_id="req-1", spec=object())
    assert index.ids == ["req-1"]
    assert view.request_id == "req-1"
    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert graph.invoke_calls == 1


def test_resume_does_not_record_another_row():
    index = _Index()
    application = IacApplication(_Graph(), request_index=index)
    application.resume("req-1", ApprovalDecision.APPROVE)
    assert index.ids == []


def test_invoke_failure_does_not_record():
    index = _Index()
    application = IacApplication(_Graph(fail=True), request_index=index)
    with pytest.raises(RuntimeError, match="workflow failed"):
        application.submit(request_id="req-1", spec=object())
    assert index.ids == []


def test_index_failure_keeps_the_workflow_view_and_logs_narrowly(caplog):
    index = _Index(error=RuntimeError(_SECRET))
    graph = _Graph()
    application = IacApplication(graph, request_index=index)
    with caplog.at_level(logging.WARNING, logger="iac_agent.persistence"):
        view = application.submit(request_id="req-1", spec=object())
    assert view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
    assert view.workflow_status is not WorkflowStatus.ERROR
    assert graph.invoke_calls == 1
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.request_id == "req-1"
    assert record.error_type == "RuntimeError"
    assert _SECRET not in caplog.text
    assert "checkpoints" not in caplog.text


def test_non_durable_outcomes_do_not_reach_submit():
    application = _Application()
    observability = FailOpenObservability(NoOpObservability())
    clarification = IntentResolutionService(
        interpreter=_Interpreter(),
        resolver=_Resolver(
            ClarificationRequired(
                request=ClarificationRequest(
                    reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
                    field="workload_type",
                    allowed_values=("api", "worker", "storage"),
                )
            )
        ),
        application=application,
        observability=observability,
    )
    clarification.submit(request_id="req-clarify", natural_language_request="hello")
    unsupported = IntentResolutionService(
        interpreter=_Interpreter(),
        resolver=_Resolver(
            UnsupportedArchitecture(
                reason=UnsupportedReason.UNSUPPORTED_CAPABILITY,
                detail="no such capability",
            )
        ),
        application=application,
        observability=observability,
    )
    unsupported.submit(request_id="req-nope", natural_language_request="hello")
    failed = IntentResolutionService(
        interpreter=_Interpreter(error=IntentProviderUnavailableError("down")),
        resolver=_Resolver(None),
        application=application,
        observability=observability,
    )
    with pytest.raises(IntentProviderUnavailableError):
        failed.submit(request_id="req-down", natural_language_request="hello")
    assert application.submits == []

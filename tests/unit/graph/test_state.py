"""Unit tests for the explicit LangGraph WorkflowState schema."""

from __future__ import annotations

import typing

from langgraph.graph import MessagesState

from iac_agent.graph.state import WorkflowState
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def test_workflow_state_is_not_messages_state_derived():
    # TypedDicts are structural-only (issubclass/isinstance are unsupported
    # for them), so the meaningful check is that WorkflowState is a
    # distinct type from MessagesState and carries no "messages" field.
    assert WorkflowState is not MessagesState
    assert "messages" not in WorkflowState.__annotations__


def test_workflow_state_declares_request_id_and_resource_spec():
    resolved = typing.get_type_hints(WorkflowState)
    assert resolved["request_id"] is str
    assert resolved["resource_spec"] is SQSResourceSpec


def test_workflow_state_declares_explicit_workflow_facts():
    annotations = WorkflowState.__annotations__
    for expected_field in (
        "workspace",
        "generated_files",
        "plan_summary",
        "platform_evaluation",
        "checkov_result",
        "security_gate",
        "workflow_status",
        "current_stage",
        "error",
    ):
        assert expected_field in annotations


def test_workflow_state_has_no_raw_terraform_plan_json_field():
    """Batch 12 correction: raw Terraform show-json output must never be
    representable in WorkflowState at all, since anything here can be
    durably checkpointed to SQLite."""
    assert "terraform_plan_json" not in WorkflowState.__annotations__

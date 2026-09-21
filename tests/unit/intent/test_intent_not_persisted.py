"""Batch 24, Task 1: `ArchitectureIntent` must never become a
checkpointed workflow type, a `WorkflowState` field, or a `WorkflowView`
field — the NL intent belongs to the application result, never to
LangGraph/SQLite state (design spec §4.4)."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.graph.state import WorkflowState
from iac_agent.persistence.checkpoints import _ALLOWED_WORKFLOW_TYPES


def test_architecture_intent_is_not_a_checkpointed_workflow_type():
    names = {qualname for _module, qualname in _ALLOWED_WORKFLOW_TYPES}
    assert "ArchitectureIntent" not in names


def test_workflow_state_has_no_intent_field():
    assert "intent" not in WorkflowState.__annotations__
    assert "architecture_intent" not in WorkflowState.__annotations__


def test_workflow_view_has_no_intent_field():
    assert "intent" not in WorkflowView.__dataclass_fields__

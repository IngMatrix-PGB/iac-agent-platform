"""Unit tests for the workflow domain models (WorkflowStatus/Stage/Error)."""

from __future__ import annotations

import dataclasses

from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus


def test_workflow_statuses_are_distinct():
    values = {s.value for s in WorkflowStatus}
    assert len(values) == len(list(WorkflowStatus))


def test_blocked_is_not_error():
    assert WorkflowStatus.BLOCKED is not WorkflowStatus.ERROR
    assert WorkflowStatus.BLOCKED.value != WorkflowStatus.ERROR.value


def test_workflow_error_does_not_contain_raw_exception_or_io_fields():
    error = WorkflowError(
        stage=WorkflowStage.TERRAFORM, error_type="TerraformCommandError", message="m"
    )
    field_names = {f.name for f in dataclasses.fields(error)}
    assert field_names == {"stage", "error_type", "message"}
    for forbidden in ("exception", "traceback", "stdout", "stderr", "env", "environment"):
        assert forbidden not in field_names


def test_workflow_error_is_immutable():
    error = WorkflowError(stage=WorkflowStage.RENDER, error_type="ValueError", message="m")
    try:
        error.message = "changed"  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised

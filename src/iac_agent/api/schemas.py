"""Public HTTP bodies. These models are not WorkflowView."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class FindingDTO(_Frozen):
    policy_id: str
    status: str
    severity: str


class PlanDTO(_Frozen):
    add: int
    change: int
    destroy: int
    destructive_change_detected: bool


class ComponentDTO(_Frozen):
    role: str
    name: str
    image_tag_mutability: str | None = None
    scan_on_push: bool | None = None


class IntentDTO(_Frozen):
    workload_type: str
    interaction_pattern: str
    capabilities: list[str]


class ResolutionDTO(_Frozen):
    outcome: str
    matched_pattern: str | None = None
    architecture: str | None = None
    name: str | None = None
    components: list[ComponentDTO] = Field(default_factory=list)
    field: str | None = None
    reason: str | None = None
    allowed_values: list[str] | None = None
    detail: str | None = None


class WorkflowErrorDTO(_Frozen):
    stage: str
    error_type: str


class PullRequestDTO(_Frozen):
    url: str


class WorkflowDTO(_Frozen):
    workflow_status: str
    current_stage: str | None
    security_status: str | None
    plan: PlanDTO | None
    findings: list[FindingDTO]
    approval_decision: str | None
    error: WorkflowErrorDTO | None
    pull_request: PullRequestDTO | None


class RequestListItem(_Frozen):
    request_id: str
    created_at: str
    workflow_status: str
    approval_available: bool
    security_status: str | None
    name: str | None


class RequestListResponse(_Frozen):
    requests: list[RequestListItem]


class RequestResponse(_Frozen):
    request_id: str
    outcome: str
    approval_available: bool
    terraform_apply: Literal["not_executed"] = "not_executed"
    intent: IntentDTO | None
    resolution: ResolutionDTO
    workflow: WorkflowDTO | None

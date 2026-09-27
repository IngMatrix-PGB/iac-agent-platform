"""Allowlisted telemetry values. Denied facts have no field to land in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GenerationTelemetry:
    request_id: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: float
    attempt_count: int
    outcome_category: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ResolutionTelemetry:
    request_id: str
    outcome: str
    workload_type: str
    interaction_pattern: str
    capabilities: tuple[str, ...]
    user_provided_hints: tuple[str, ...]
    matched_pattern: str | None = None
    resolved_type: str | None = None
    clarification_reason: str | None = None
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class FindingTelemetry:
    policy_id: str
    status: str
    severity: str


@dataclass(frozen=True)
class WorkflowTelemetry:
    request_id: str
    kind: Literal["submit", "resume", "terminal"]
    workflow_status: str
    current_stage: str | None
    security_status: str | None
    add_count: int | None
    change_count: int | None
    destroy_count: int | None
    destructive_change_detected: bool | None
    findings: tuple[FindingTelemetry, ...]
    approval_decision: str | None
    error_stage: str | None
    error_type: str | None
    published: bool

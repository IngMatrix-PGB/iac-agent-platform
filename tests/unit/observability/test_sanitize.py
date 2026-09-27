"""Defense-in-depth scrub of strings that are already on a telemetry model."""

from __future__ import annotations

import pytest

from iac_agent.observability.models import GenerationTelemetry, WorkflowTelemetry
from iac_agent.observability.sanitize import sanitize_telemetry


def _generation(**overrides: object) -> GenerationTelemetry:
    values: dict[str, object] = {
        "request_id": "req-001",
        "provider": "openai",
        "model": "gpt-test",
        "prompt_version": "4",
        "latency_ms": 1.0,
        "attempt_count": 1,
        "outcome_category": "ok",
    }
    values.update(overrides)
    return GenerationTelemetry(**values)  # type: ignore[arg-type]


def _terminal(**overrides: object) -> WorkflowTelemetry:
    values: dict[str, object] = {
        "request_id": "req-001",
        "kind": "terminal",
        "workflow_status": "error",
        "current_stage": "error",
        "security_status": None,
        "add_count": None,
        "change_count": None,
        "destroy_count": None,
        "destructive_change_detected": None,
        "findings": (),
        "approval_decision": None,
        "error_stage": "plan_analysis",
        "error_type": "TerraformCommandError",
        "published": False,
    }
    values.update(overrides)
    return WorkflowTelemetry(**values)  # type: ignore[arg-type]


def test_secret_patterns_are_replaced_on_allowlisted_strings():
    cleaned = sanitize_telemetry(
        _generation(model="sk-live-secret", outcome_category="Bearer abc.def.ghi")
    )
    assert cleaned.model == "[redacted]"
    assert cleaned.outcome_category == "[redacted]"
    assert cleaned.request_id == "req-001"


def test_env_var_names_and_key_prefixes_are_replaced():
    cleaned = sanitize_telemetry(_terminal(error_type="AWS_SECRET_ACCESS_KEY"))
    assert cleaned.error_type == "[redacted]"


@pytest.mark.parametrize(
    "needle",
    [
        "sk-lf-abc",
        "ghp_abc",
        "github_pat_abc",
        "AKIAIOSFODNN7EXAMPLE",
        "ASIAIOSFODNN7EXAMPLE",
        "BEGIN PRIVATE KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature",
    ],
)
def test_planted_secret_needles_are_replaced(needle: str):
    cleaned = sanitize_telemetry(_generation(model=needle))
    assert cleaned.model == "[redacted]"
    assert needle not in repr(cleaned)


def test_ordinary_enums_pass_through():
    event = _generation()
    assert sanitize_telemetry(event) == event

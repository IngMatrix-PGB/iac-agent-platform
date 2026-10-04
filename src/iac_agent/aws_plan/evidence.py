"""Bounded V3 evidence. Raw plans, credentials, and proposal HCL stay out."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iac_agent.aws_plan.outcomes import TerminalOutcome


@dataclass(frozen=True)
class V3Evidence:
    schema_version: str
    purpose: str
    terminal_outcome: TerminalOutcome
    workflow_run_id: str
    workflow_run_attempt: str
    repository_id: str
    pr_number: int
    proposal_sha: str
    executor_sha: str
    request_id: str
    target: Mapping[str, str]
    terraform: Mapping[str, str]
    plan: Mapping[str, Any]
    security: Mapping[str, Any]
    profile_candidate_action: str | None


def evidence_to_json(evidence: V3Evidence) -> str:
    payload = {
        "schema_version": evidence.schema_version,
        "purpose": evidence.purpose,
        "terminal_outcome": evidence.terminal_outcome.value,
        "workflow_run_id": evidence.workflow_run_id,
        "workflow_run_attempt": evidence.workflow_run_attempt,
        "repository_id": evidence.repository_id,
        "pr_number": evidence.pr_number,
        "proposal_sha": evidence.proposal_sha,
        "executor_sha": evidence.executor_sha,
        "request_id": evidence.request_id,
        "target": dict(evidence.target),
        "terraform": dict(evidence.terraform),
        "plan": _json_ready(dict(evidence.plan)),
        "security": _json_ready(dict(evidence.security)),
        "profile_candidate_action": evidence.profile_candidate_action,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write_evidence(path: Path, evidence: V3Evidence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evidence_to_json(evidence), encoding="utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value

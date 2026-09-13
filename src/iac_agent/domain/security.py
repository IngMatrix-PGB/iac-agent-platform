"""Domain models for deterministic security/policy findings.

These models describe the *outcome* of policy evaluation (pass/warn/
block, severity, source) — they carry no logic themselves. Evaluation
logic lives in ``iac_agent.policies``. Nothing here decides anything;
it only represents a decision already made by deterministic Python
code elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PolicyStatus(StrEnum):
    """The outcome of evaluating one policy against a request."""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class SecuritySeverity(StrEnum):
    """How serious a finding is, independent of whether it blocks."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingSource(StrEnum):
    """Where a finding originated.

    Only PLATFORM_POLICY is ever emitted as of Batch 7. The other
    members name sources this architecture already knows it will add
    later (Pydantic-contract-level findings, Terraform validate/plan
    facts surfaced as findings, and Checkov) so that later batches can
    extend ``source`` without changing every existing call site — no
    adapter exists for any of them yet.
    """

    PYDANTIC = "pydantic"
    TERRAFORM = "terraform"
    PLAN_ANALYZER = "plan_analyzer"
    CHECKOV = "checkov"
    PLATFORM_POLICY = "platform_policy"


@dataclass(frozen=True)
class SecurityFinding:
    """One normalized policy outcome for one policy against one request.

    ``blocking`` is deliberately a derived property, not a stored
    field — this makes the ``status == BLOCK <=> blocking`` invariant
    impossible to violate by construction, rather than merely validated
    after the fact.
    """

    policy_id: str
    severity: SecuritySeverity
    status: PolicyStatus
    resource: str | None
    message: str
    source: FindingSource

    @property
    def blocking(self) -> bool:
        return self.status is PolicyStatus.BLOCK


@dataclass(frozen=True)
class PolicyEvaluation:
    """The aggregate result of evaluating every applicable policy.

    ``findings`` is normalized to a deterministic order (by
    ``policy_id``, then ``resource``) on construction, regardless of
    the order supplied — so two evaluations built from the same
    logical findings, in any order, are equal.

    ``overall_status`` is a derived property, never a stored field, so
    it can never drift from ``findings``.
    """

    findings: tuple[SecurityFinding, ...]

    def __post_init__(self) -> None:
        normalized = tuple(sorted(self.findings, key=lambda f: (f.policy_id, f.resource or "")))
        object.__setattr__(self, "findings", normalized)

    @property
    def overall_status(self) -> PolicyStatus:
        if any(f.status is PolicyStatus.BLOCK for f in self.findings):
            return PolicyStatus.BLOCK
        if any(f.status is PolicyStatus.WARN for f in self.findings):
            return PolicyStatus.WARN
        return PolicyStatus.PASS

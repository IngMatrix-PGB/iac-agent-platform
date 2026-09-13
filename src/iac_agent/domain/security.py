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


@dataclass(frozen=True)
class SecurityGateResult:
    """The aggregate security decision combining first-party platform
    policy findings with external scanner (Checkov) findings.

    This is a pure aggregator: it does not evaluate anything itself,
    only combines and orders findings already produced elsewhere (see
    ``iac_agent.security.gate.evaluate_security_gate``).

    ``findings`` is normalized on construction — sorted by
    ``(source, policy_id, resource or "", message)`` — so two gate
    results built from the same logical findings, in any order, are
    equal. ``overall_status`` and the count properties are all derived,
    never stored, so none of them can drift from ``findings``.

    There is deliberately no ``can_proceed`` (or similarly named)
    boolean here: in Phase 1, WARN is a legitimate outcome that may
    still require human review once HITL exists, so collapsing
    PASS/WARN into a single "may proceed" flag would risk being read as
    "no further review needed" when that is not yet true. Consumers
    should branch on ``overall_status`` directly.
    """

    findings: tuple[SecurityFinding, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                self.findings, key=lambda f: (f.source, f.policy_id, f.resource or "", f.message)
            )
        )
        object.__setattr__(self, "findings", normalized)

    @property
    def overall_status(self) -> PolicyStatus:
        if any(f.status is PolicyStatus.BLOCK for f in self.findings):
            return PolicyStatus.BLOCK
        if any(f.status is PolicyStatus.WARN for f in self.findings):
            return PolicyStatus.WARN
        return PolicyStatus.PASS

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def pass_count(self) -> int:
        return sum(1 for f in self.findings if f.status is PolicyStatus.PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.status is PolicyStatus.WARN)

    @property
    def block_count(self) -> int:
        return sum(1 for f in self.findings if f.status is PolicyStatus.BLOCK)

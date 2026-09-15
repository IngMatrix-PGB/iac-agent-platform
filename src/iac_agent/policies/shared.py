"""The one platform-wide policy shared by every request kind — single-
AWS-resource requests (`iac_agent.policies.platform`) and multi-
resource composition requests (`iac_agent.policies.composition`) alike
(Batch 19).

`TF_NO_DESTRUCTIVE_CHANGES` never touches a resource or composition
spec at all, only a `PlanSummary` — it is exactly as meaningful for a
10-resource composition plan as for a single-resource one. Promoted out
of `iac_agent.policies.platform` (where it originated in Batch 7) into
its own module once a second dispatcher (`iac_agent.policies.
composition`) needed it too, rather than being duplicated or imported
as a private name across modules.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import FindingSource, PolicyStatus, SecurityFinding, SecuritySeverity

TF_NO_DESTRUCTIVE_CHANGES = "TF_NO_DESTRUCTIVE_CHANGES"


def evaluate_destructive_policy(plan_summary: PlanSummary) -> SecurityFinding:
    """TF_NO_DESTRUCTIVE_CHANGES — blocks on any destructive plan action.

    A REPLACE is destructive (it contains a delete) exactly as
    established in Batch 6's `PlanSummary` semantics; no exception is
    made for it here. `resource` is left `None` because this finding
    can summarize more than one resource — the destroyed addresses are
    named in the message instead, never with raw before/after values.
    """
    if not plan_summary.destructive_change_detected:
        return SecurityFinding(
            policy_id=TF_NO_DESTRUCTIVE_CHANGES,
            severity=SecuritySeverity.CRITICAL,
            status=PolicyStatus.PASS,
            resource=None,
            message="Terraform plan contains no destructive changes.",
            source=FindingSource.PLATFORM_POLICY,
        )
    addresses = ", ".join(sorted(plan_summary.resources_to_destroy))
    return SecurityFinding(
        policy_id=TF_NO_DESTRUCTIVE_CHANGES,
        severity=SecuritySeverity.CRITICAL,
        status=PolicyStatus.BLOCK,
        resource=None,
        message=f"Terraform plan contains destructive changes: {addresses}.",
        source=FindingSource.PLATFORM_POLICY,
    )

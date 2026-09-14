"""Resource-aware Checkov scan profiles (Batch 16.5).

`CheckovAdapter` (`iac_agent.security.checkov`) is deliberately generic
— it never infers a resource type and carries no default skip list of
its own. This module is the one place that maps a `ResourceType` to
the specific, narrow `CheckovScanProfile` its requests are permitted to
use, with each skipped check carrying an inline architectural-scope
rationale. Mirrors the same `ResourceType`-keyed-mapping discipline
already used by
`iac_agent.policies.platform.REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE`
— a small explicit table, not a plugin/registry framework.
"""

from __future__ import annotations

from iac_agent.domain.resource import ResourceType
from iac_agent.security.checkov import CheckovScanProfile

#: Verified empirically (2026-09, Checkov 3.3.13, real scan of the
#: trusted S3 module's secure baseline output — resource_count=5,
#: passed=13, failed=4): exactly these four checks fail, one per
#: documented Phase 2 non-goal (see docs/resources/s3.md). Every skip
#: below states an architectural scope reason, never "skip because
#: Checkov fails" — since every Checkov-reported failed check maps
#: unconditionally to `PolicyStatus.BLOCK` (no WARN path exists for
#: Checkov findings), leaving these unskipped would mean no S3 request
#: could ever reach human approval, regardless of how secure the
#: Phase 2 baseline actually is.
_S3_SKIPPED_CHECKS: tuple[str, ...] = (
    # "Ensure the S3 bucket has access logging enabled" — access
    # logging is a documented Phase 2 non-goal, not implemented.
    "CKV_AWS_18",
    # "Ensure that an S3 bucket has a lifecycle configuration" —
    # lifecycle rules are a documented Phase 2 non-goal.
    "CKV2_AWS_61",
    # "Ensure S3 buckets should have event notifications enabled" —
    # event notifications are a documented Phase 2 non-goal.
    "CKV2_AWS_62",
    # "Ensure that S3 bucket has cross-region replication enabled" —
    # cross-region replication is a documented Phase 2 non-goal.
    "CKV_AWS_144",
)

#: SQS carries no skip list at all — its trusted module has produced a
#: clean Checkov scan since Batch 8/9 (see
#: tests/integration/test_checkov_integration.py and
#: tests/integration/test_security_gate_integration.py, both of which
#: run the real scanner with no profile and assert a PASS result).
#: Listed explicitly (not merely "absent from the mapping") so a
#: reviewer can see at a glance that SQS was a deliberate zero-skip
#: decision, not an oversight.
_PROFILES_BY_RESOURCE_TYPE: dict[ResourceType, CheckovScanProfile] = {
    ResourceType.SQS: CheckovScanProfile(skipped_checks=()),
    ResourceType.S3: CheckovScanProfile(skipped_checks=_S3_SKIPPED_CHECKS),
}


def checkov_profile_for(resource_type: ResourceType) -> CheckovScanProfile:
    """The Checkov scan profile for `resource_type`.

    Fails closed (raises `ValueError`) for any resource type without an
    explicit, reviewed profile registered above — a new `ResourceType`
    member added without a corresponding profile decision here must
    never silently receive skips, and must never silently receive the
    strict zero-skip profile either; both are policy decisions someone
    has to actually make.
    """
    try:
        return _PROFILES_BY_RESOURCE_TYPE[resource_type]
    except KeyError:
        raise ValueError(
            f"no Checkov scan profile registered for resource type: {resource_type!r}"
        ) from None

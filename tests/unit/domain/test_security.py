"""Unit tests for the SecurityFinding / PolicyEvaluation domain models."""

from __future__ import annotations

from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)


def _finding(policy_id, status, resource=None, severity=SecuritySeverity.MEDIUM):
    return SecurityFinding(
        policy_id=policy_id,
        severity=severity,
        status=status,
        resource=resource,
        message=f"{policy_id} -> {status.value}",
        source=FindingSource.PLATFORM_POLICY,
    )


# ---------------------------------------------------------------------------
# SecurityFinding model
# ---------------------------------------------------------------------------


def test_pass_finding_is_non_blocking():
    finding = _finding("P", PolicyStatus.PASS)
    assert finding.blocking is False


def test_warn_finding_is_non_blocking():
    finding = _finding("P", PolicyStatus.WARN)
    assert finding.blocking is False


def test_block_finding_is_blocking():
    finding = _finding("P", PolicyStatus.BLOCK)
    assert finding.blocking is True


def test_contradictory_status_blocking_state_cannot_exist():
    """`blocking` is a derived property, not a stored field, so there is
    no constructor argument through which a contradictory
    (status, blocking) pair could ever be supplied."""
    for status in (PolicyStatus.PASS, PolicyStatus.WARN, PolicyStatus.BLOCK):
        finding = _finding("P", status)
        assert finding.blocking == (status is PolicyStatus.BLOCK)
    assert "blocking" not in SecurityFinding.__dataclass_fields__


def test_source_is_platform_policy():
    finding = _finding("P", PolicyStatus.PASS)
    assert finding.source is FindingSource.PLATFORM_POLICY


# ---------------------------------------------------------------------------
# PolicyEvaluation aggregate
# ---------------------------------------------------------------------------


def test_all_pass_gives_overall_pass():
    evaluation = PolicyEvaluation(
        findings=(_finding("A", PolicyStatus.PASS), _finding("B", PolicyStatus.PASS))
    )
    assert evaluation.overall_status is PolicyStatus.PASS


def test_pass_and_warn_gives_overall_warn():
    evaluation = PolicyEvaluation(
        findings=(_finding("A", PolicyStatus.PASS), _finding("B", PolicyStatus.WARN))
    )
    assert evaluation.overall_status is PolicyStatus.WARN


def test_pass_and_block_gives_overall_block():
    evaluation = PolicyEvaluation(
        findings=(_finding("A", PolicyStatus.PASS), _finding("B", PolicyStatus.BLOCK))
    )
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_warn_and_block_gives_overall_block():
    evaluation = PolicyEvaluation(
        findings=(_finding("A", PolicyStatus.WARN), _finding("B", PolicyStatus.BLOCK))
    )
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_findings_order_is_deterministic_regardless_of_input_order():
    ordered = PolicyEvaluation(
        findings=(
            _finding("A", PolicyStatus.PASS),
            _finding("B", PolicyStatus.PASS),
            _finding("C", PolicyStatus.PASS),
        )
    )
    reordered = PolicyEvaluation(
        findings=(
            _finding("C", PolicyStatus.PASS),
            _finding("A", PolicyStatus.PASS),
            _finding("B", PolicyStatus.PASS),
        )
    )

    assert [f.policy_id for f in ordered.findings] == ["A", "B", "C"]
    assert ordered == reordered

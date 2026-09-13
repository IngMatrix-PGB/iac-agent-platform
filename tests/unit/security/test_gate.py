"""Unit tests for the deterministic security gate.

No Terraform, Checkov, AWS, network, or LLM dependency anywhere in this
file — the gate consumes only already-constructed PolicyEvaluation and
CheckovScanResult values. Real end-to-end evidence is exercised
separately by tests/integration/test_security_gate_integration.py.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.policies.platform import (
    SQS_DLQ_RECOMMENDED,
    SQS_ENCRYPTION_REQUIRED,
    TF_NO_DESTRUCTIVE_CHANGES,
)
from iac_agent.security import gate as gate_module
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import SecurityGateError, evaluate_security_gate


def _finding(
    policy_id,
    status,
    *,
    resource=None,
    severity=SecuritySeverity.MEDIUM,
    source=FindingSource.PLATFORM_POLICY,
    message=None,
):
    return SecurityFinding(
        policy_id=policy_id,
        severity=severity,
        status=status,
        resource=resource,
        message=message or f"{policy_id} -> {status.value}",
        source=source,
    )


def _platform_eval(
    encryption=PolicyStatus.PASS,
    dlq=PolicyStatus.PASS,
    destructive=PolicyStatus.PASS,
    extra_findings=(),
):
    findings = (
        _finding(
            SQS_ENCRYPTION_REQUIRED,
            encryption,
            resource="order-events",
            severity=SecuritySeverity.HIGH,
        ),
        _finding(
            SQS_DLQ_RECOMMENDED, dlq, resource="order-events", severity=SecuritySeverity.MEDIUM
        ),
        _finding(
            TF_NO_DESTRUCTIVE_CHANGES,
            destructive,
            resource=None,
            severity=SecuritySeverity.CRITICAL,
        ),
        *extra_findings,
    )
    return PolicyEvaluation(findings=findings)


def _clean_checkov():
    return CheckovScanResult(
        findings=(), passed_checks=5, failed_checks=0, skipped_checks=0, scanner_version="3.3.13"
    )


def _checkov_with_failure(check_id="CKV_AWS_27", resource="module.queue.aws_sqs_queue.this"):
    finding = _finding(
        check_id,
        PolicyStatus.BLOCK,
        resource=resource,
        severity=SecuritySeverity.HIGH,
        source=FindingSource.CHECKOV,
        message=f"Checkov {check_id} failed.",
    )
    return CheckovScanResult(
        findings=(finding,),
        passed_checks=4,
        failed_checks=1,
        skipped_checks=0,
        scanner_version="3.3.13",
    )


# ---------------------------------------------------------------------------
# Basic aggregation
# ---------------------------------------------------------------------------


def test_three_platform_pass_and_clean_checkov_gives_pass():
    result = evaluate_security_gate(_platform_eval(), _clean_checkov())
    assert result.overall_status is PolicyStatus.PASS


def test_platform_warn_and_clean_checkov_gives_warn():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _clean_checkov())
    assert result.overall_status is PolicyStatus.WARN


def test_platform_block_and_clean_checkov_gives_block():
    result = evaluate_security_gate(
        _platform_eval(destructive=PolicyStatus.BLOCK), _clean_checkov()
    )
    assert result.overall_status is PolicyStatus.BLOCK


def test_platform_pass_and_checkov_block_gives_block():
    result = evaluate_security_gate(_platform_eval(), _checkov_with_failure())
    assert result.overall_status is PolicyStatus.BLOCK


def test_platform_warn_and_checkov_block_gives_block():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _checkov_with_failure())
    assert result.overall_status is PolicyStatus.BLOCK


def test_platform_block_and_checkov_block_gives_block():
    result = evaluate_security_gate(
        _platform_eval(destructive=PolicyStatus.BLOCK), _checkov_with_failure()
    )
    assert result.overall_status is PolicyStatus.BLOCK


# ---------------------------------------------------------------------------
# Finding preservation
# ---------------------------------------------------------------------------


def test_platform_findings_preserved_unchanged():
    platform = _platform_eval()
    result = evaluate_security_gate(platform, _clean_checkov())

    for original in platform.findings:
        assert original in result.findings


def test_checkov_findings_preserved_unchanged():
    checkov = _checkov_with_failure()
    result = evaluate_security_gate(_platform_eval(), checkov)

    for original in checkov.findings:
        assert original in result.findings


def test_platform_and_checkov_findings_for_same_resource_both_remain():
    result = evaluate_security_gate(
        _platform_eval(), _checkov_with_failure(resource="module.queue.aws_sqs_queue.this")
    )
    resources = [f.resource for f in result.findings]
    assert resources.count("module.queue.aws_sqs_queue.this") >= 1
    assert resources.count("order-events") >= 1
    assert len(result.findings) == 4  # 3 platform + 1 checkov


def test_same_message_from_different_policy_ids_does_not_deduplicate():
    extra = (
        _finding("CUSTOM_ONE", PolicyStatus.PASS, message="identical message", resource="r"),
        _finding("CUSTOM_TWO", PolicyStatus.PASS, message="identical message", resource="r"),
    )
    platform = _platform_eval(extra_findings=extra)
    result = evaluate_security_gate(platform, _clean_checkov())

    assert sum(1 for f in result.findings if f.message == "identical message") == 2


def test_same_policy_id_from_different_source_does_not_deduplicate():
    # A platform-policy-owned ID happening to collide with a distinct
    # Checkov-sourced finding of the "same" policy_id string must not
    # be collapsed — source is part of the identity.
    checkov = CheckovScanResult(
        findings=(
            _finding(
                SQS_ENCRYPTION_REQUIRED,
                PolicyStatus.BLOCK,
                resource="order-events",
                severity=SecuritySeverity.HIGH,
                source=FindingSource.CHECKOV,
                message="a distinct checkov-sourced finding",
            ),
        ),
        passed_checks=4,
        failed_checks=1,
        skipped_checks=0,
        scanner_version="3.3.13",
    )
    result = evaluate_security_gate(_platform_eval(), checkov)

    matching = [f for f in result.findings if f.policy_id == SQS_ENCRYPTION_REQUIRED]
    assert len(matching) == 2
    assert {f.source for f in matching} == {FindingSource.PLATFORM_POLICY, FindingSource.CHECKOV}


# ---------------------------------------------------------------------------
# Exact duplicates
# ---------------------------------------------------------------------------


def test_exact_duplicate_finding_is_deduplicated():
    dup = _finding("CUSTOM_DUP", PolicyStatus.PASS, resource="r", message="m")
    platform = _platform_eval(extra_findings=(dup, dup))
    result = evaluate_security_gate(platform, _clean_checkov())

    assert sum(1 for f in result.findings if f.policy_id == "CUSTOM_DUP") == 1


def test_output_ordering_is_deterministic_after_deduplication():
    dup = _finding("CUSTOM_DUP", PolicyStatus.PASS, resource="r", message="m")
    platform = _platform_eval(extra_findings=(dup, dup))
    result = evaluate_security_gate(platform, _clean_checkov())

    keys = [(f.source.value, f.policy_id, f.resource or "", f.message) for f in result.findings]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_pass_only_gives_pass():
    assert (
        evaluate_security_gate(_platform_eval(), _clean_checkov()).overall_status
        is PolicyStatus.PASS
    )


def test_warn_present_with_no_block_gives_warn():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _clean_checkov())
    assert result.overall_status is PolicyStatus.WARN


def test_any_block_gives_block():
    result = evaluate_security_gate(_platform_eval(), _checkov_with_failure())
    assert result.overall_status is PolicyStatus.BLOCK


# ---------------------------------------------------------------------------
# Derived counts
# ---------------------------------------------------------------------------


def test_finding_count_is_correct():
    result = evaluate_security_gate(_platform_eval(), _checkov_with_failure())
    assert result.finding_count == 4


def test_pass_count_is_correct():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _checkov_with_failure())
    assert result.pass_count == 2  # encryption PASS, destructive PASS


def test_warn_count_is_correct():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _checkov_with_failure())
    assert result.warn_count == 1


def test_block_count_is_correct():
    result = evaluate_security_gate(_platform_eval(dlq=PolicyStatus.WARN), _checkov_with_failure())
    assert result.block_count == 1  # only the checkov failure


# ---------------------------------------------------------------------------
# Platform completeness (fail-closed)
# ---------------------------------------------------------------------------


def test_missing_encryption_policy_raises():
    platform = PolicyEvaluation(
        findings=(
            _finding(SQS_DLQ_RECOMMENDED, PolicyStatus.PASS, resource="x"),
            _finding(TF_NO_DESTRUCTIVE_CHANGES, PolicyStatus.PASS),
        )
    )
    with pytest.raises(SecurityGateError, match=SQS_ENCRYPTION_REQUIRED):
        evaluate_security_gate(platform, _clean_checkov())


def test_missing_dlq_policy_raises():
    platform = PolicyEvaluation(
        findings=(
            _finding(SQS_ENCRYPTION_REQUIRED, PolicyStatus.PASS, resource="x"),
            _finding(TF_NO_DESTRUCTIVE_CHANGES, PolicyStatus.PASS),
        )
    )
    with pytest.raises(SecurityGateError, match=SQS_DLQ_RECOMMENDED):
        evaluate_security_gate(platform, _clean_checkov())


def test_missing_destructive_policy_raises():
    platform = PolicyEvaluation(
        findings=(
            _finding(SQS_ENCRYPTION_REQUIRED, PolicyStatus.PASS, resource="x"),
            _finding(SQS_DLQ_RECOMMENDED, PolicyStatus.PASS, resource="x"),
        )
    )
    with pytest.raises(SecurityGateError, match=TF_NO_DESTRUCTIVE_CHANGES):
        evaluate_security_gate(platform, _clean_checkov())


def test_empty_policy_evaluation_raises():
    with pytest.raises(SecurityGateError):
        evaluate_security_gate(PolicyEvaluation(findings=()), _clean_checkov())


def test_duplicate_required_platform_policy_raises():
    platform = PolicyEvaluation(
        findings=(
            _finding(SQS_ENCRYPTION_REQUIRED, PolicyStatus.PASS, resource="x"),
            _finding(SQS_ENCRYPTION_REQUIRED, PolicyStatus.PASS, resource="y"),
            _finding(SQS_DLQ_RECOMMENDED, PolicyStatus.PASS, resource="x"),
            _finding(TF_NO_DESTRUCTIVE_CHANGES, PolicyStatus.PASS),
        )
    )
    with pytest.raises(SecurityGateError, match="duplicated"):
        evaluate_security_gate(platform, _clean_checkov())


def test_required_policy_with_wrong_source_raises():
    platform = PolicyEvaluation(
        findings=(
            _finding(
                SQS_ENCRYPTION_REQUIRED,
                PolicyStatus.PASS,
                resource="x",
                source=FindingSource.CHECKOV,
            ),
            _finding(SQS_DLQ_RECOMMENDED, PolicyStatus.PASS, resource="x"),
            _finding(TF_NO_DESTRUCTIVE_CHANGES, PolicyStatus.PASS),
        )
    )
    with pytest.raises(SecurityGateError, match="source"):
        evaluate_security_gate(platform, _clean_checkov())


# ---------------------------------------------------------------------------
# Scanner consistency
# ---------------------------------------------------------------------------


def test_clean_checkov_result_with_zero_findings_is_accepted():
    result = evaluate_security_gate(_platform_eval(), _clean_checkov())
    assert result.overall_status is PolicyStatus.PASS


def test_failed_checkov_result_with_normalized_block_finding_is_accepted():
    result = evaluate_security_gate(_platform_eval(), _checkov_with_failure())
    assert any(f.source is FindingSource.CHECKOV for f in result.findings)


def test_inconsistent_checkov_counts_are_rejected():
    inconsistent = CheckovScanResult(
        findings=(), passed_checks=4, failed_checks=1, skipped_checks=0, scanner_version="3.3.13"
    )
    with pytest.raises(SecurityGateError):
        evaluate_security_gate(_platform_eval(), inconsistent)


def test_gate_never_invents_a_checkov_pass_finding():
    result = evaluate_security_gate(_platform_eval(), _clean_checkov())
    checkov_findings = [f for f in result.findings if f.source is FindingSource.CHECKOV]
    assert checkov_findings == []


# ---------------------------------------------------------------------------
# Purity / safety
# ---------------------------------------------------------------------------


def test_gate_module_imports_no_forbidden_dependencies():
    tree = ast.parse(inspect.getsource(gate_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"subprocess", "langchain", "langgraph", "boto3", "requests", "httpx", "os"}
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_gate_does_not_import_plan_analyzer_or_sqs_contract_modules():
    """The gate must not import iac_agent.domain.plan (PlanSummary),
    iac_agent.execution.plan_analyzer (raw plan JSON), or the SQS
    contract module — those are already fully consumed upstream."""
    tree = ast.parse(inspect.getsource(gate_module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_modules = {
        "iac_agent.domain.plan",
        "iac_agent.execution.plan_analyzer",
        "iac_agent.execution.terraform_runner",
        "iac_agent.providers.aws.sqs.contract",
    }
    assert not (imported_modules & forbidden_modules), imported_modules & forbidden_modules


def test_error_text_does_not_dump_full_findings_or_repr():
    platform = PolicyEvaluation(findings=())
    with pytest.raises(SecurityGateError) as exc_info:
        evaluate_security_gate(platform, _clean_checkov())

    message = str(exc_info.value)
    assert "SecurityFinding(" not in message
    assert "PolicyEvaluation(" not in message


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_reordered_platform_findings_produce_equal_gate_result():
    findings = (
        _finding(
            SQS_ENCRYPTION_REQUIRED, PolicyStatus.PASS, resource="x", severity=SecuritySeverity.HIGH
        ),
        _finding(
            SQS_DLQ_RECOMMENDED, PolicyStatus.PASS, resource="x", severity=SecuritySeverity.MEDIUM
        ),
        _finding(TF_NO_DESTRUCTIVE_CHANGES, PolicyStatus.PASS, severity=SecuritySeverity.CRITICAL),
    )
    a = evaluate_security_gate(PolicyEvaluation(findings=findings), _clean_checkov())
    b = evaluate_security_gate(
        PolicyEvaluation(findings=tuple(reversed(findings))), _clean_checkov()
    )
    assert a == b


def test_reordered_checkov_findings_produce_equal_gate_result():
    f1 = _finding(
        "CKV_AWS_1",
        PolicyStatus.BLOCK,
        resource="a",
        source=FindingSource.CHECKOV,
        severity=SecuritySeverity.HIGH,
    )
    f2 = _finding(
        "CKV_AWS_2",
        PolicyStatus.BLOCK,
        resource="b",
        source=FindingSource.CHECKOV,
        severity=SecuritySeverity.HIGH,
    )

    checkov_ab = CheckovScanResult(
        findings=(f1, f2),
        passed_checks=3,
        failed_checks=2,
        skipped_checks=0,
        scanner_version="3.3.13",
    )
    checkov_ba = CheckovScanResult(
        findings=(f2, f1),
        passed_checks=3,
        failed_checks=2,
        skipped_checks=0,
        scanner_version="3.3.13",
    )

    a = evaluate_security_gate(_platform_eval(), checkov_ab)
    b = evaluate_security_gate(_platform_eval(), checkov_ba)
    assert a == b


def test_repeated_evaluation_produces_equal_result():
    platform = _platform_eval()
    checkov = _clean_checkov()

    assert evaluate_security_gate(platform, checkov) == evaluate_security_gate(platform, checkov)


# ---------------------------------------------------------------------------
# Model shape
# ---------------------------------------------------------------------------


def test_security_gate_result_type():
    result = evaluate_security_gate(_platform_eval(), _clean_checkov())
    assert isinstance(result, SecurityGateResult)
    assert not hasattr(result, "can_proceed")

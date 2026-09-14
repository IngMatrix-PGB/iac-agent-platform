"""Integration-style test: the entire S3 golden dataset through the
deterministic eval runner.

Mirrors tests/integration/test_sqs_golden_evals.py — "integration" in
the sense of exercising the full runner -> loader -> evaluators ->
domain-model chain together end-to-end, not in the sense of using real
external tools (that is proven separately by the one optional
real-tool eval below, and by tests/integration/test_s3_workflow_integration.py).
"""

from __future__ import annotations

from evals.scenarios.s3_runner import format_summary, run_s3_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "basic_secure_bucket",
    "versioning_disabled_warn",
    "kms_encrypted_bucket",
    "invalid_uppercase_name",
    "invalid_too_short_name",
    "invalid_too_long_name",
    "invalid_ipv4_shaped_name",
    "invalid_adjacent_periods_name",
    "attempted_encryption_disable",
    "attempted_public_access_unblock",
    "valid_tags_bucket",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_s3_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

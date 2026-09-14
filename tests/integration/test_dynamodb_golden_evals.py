"""Integration-style test: the entire DynamoDB golden dataset through the
deterministic eval runner (Batch 17).

Mirrors tests/integration/test_s3_golden_evals.py — "integration" in
the sense of exercising the full runner -> loader -> evaluators ->
domain-model chain together end-to-end, not in the sense of using real
external tools (that is proven separately by the one optional
real-tool eval below, and by
tests/integration/test_dynamodb_workflow_integration.py).
"""

from __future__ import annotations

from evals.scenarios.dynamodb_runner import format_summary, run_dynamodb_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "secure_basic_table",
    "partition_key_string",
    "partition_key_number",
    "partition_and_sort_key",
    "invalid_duplicate_partition_and_sort_key_name",
    "invalid_table_name_too_short",
    "invalid_key_type",
    "pitr_disabled_warn",
    "deletion_protection_disabled_warn",
    "attempted_encryption_disable",
    "valid_tags_table",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_dynamodb_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

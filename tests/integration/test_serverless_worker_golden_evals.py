"""Integration-style test: the entire serverless-worker golden dataset
through the deterministic eval runner (Batch 19).

Mirrors tests/integration/test_lambda_golden_evals.py — "integration"
in the sense of exercising the full runner -> loader -> evaluators ->
domain-model chain together end-to-end, not in the sense of using real
external tools (that is proven separately by the one optional real-tool
eval below, and by
tests/integration/test_serverless_worker_workflow_integration.py).
"""

from __future__ import annotations

from evals.scenarios.serverless_worker_runner import (
    format_summary,
    run_serverless_worker_golden_evals,
)

_REQUIRED_SCENARIO_IDS = {
    "secure_basic_composition",
    "custom_queue_name",
    "custom_lambda_name",
    "custom_table_name",
    "arm64_lambda",
    "x86_64_lambda",
    "tracing_pass_through_warns",
    "no_reserved_concurrency_warns",
    "pitr_disabled_warns",
    "deletion_protection_disabled_warns",
    "invalid_nested_queue_spec",
    "invalid_nested_lambda_spec",
    "invalid_nested_dynamodb_spec",
    "invalid_duplicate_identifiers",
    "deterministic_defaults",
    "relationship_iam_scope",
    "event_source_mapping_present",
    "table_env_var_present",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_serverless_worker_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

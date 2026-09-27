"""Integration-style test: the entire api_lambda_dynamodb golden
dataset through the deterministic eval runner (Batch 26).

Mirrors tests/integration/test_api_lambda_golden_evals.py — "integration"
in the sense of exercising the full runner -> loader -> evaluators ->
domain-model chain together end-to-end, not in the sense of using real
external tools. This one is fully Gate-A-safe (no `pytestmark`, unlike
the real-tool-marked tests): its `security_status` evaluator never
calls `composition_checkov_profile_for` (see
`evals.evaluators.api_lambda_dynamodb`'s own module docstring), so it
does not depend on Gate B's empirical Checkov discovery (Task 16) at
all.
"""

from __future__ import annotations

from evals.scenarios.api_lambda_dynamodb_runner import (
    format_summary,
    run_api_lambda_dynamodb_golden_evals,
)

_REQUIRED_SCENARIO_IDS = {
    "secure_defaults",
    "get_route",
    "tracing_pass_through_warns",
    "no_reserved_concurrency_warns",
    "pitr_disabled_warns",
    "deletion_protection_disabled_warns",
    "invalid_route_missing_slash",
    "invalid_route_method",
    "invalid_duplicate_api_and_table_names",
    "invalid_missing_partition_key",
    "deterministic_defaults",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_api_lambda_dynamodb_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

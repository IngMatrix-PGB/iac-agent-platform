"""Integration-style test: the entire Lambda golden dataset through the
deterministic eval runner (Batch 18).

Mirrors tests/integration/test_dynamodb_golden_evals.py — "integration"
in the sense of exercising the full runner -> loader -> evaluators ->
domain-model chain together end-to-end, not in the sense of using real
external tools (that is proven separately by the one optional real-tool
eval below, and by tests/integration/test_lambda_workflow_integration.py).
"""

from __future__ import annotations

from evals.scenarios.lambda_runner import format_summary, run_lambda_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "secure_basic_function",
    "architecture_x86_64",
    "architecture_arm64_explicit",
    "valid_minimum_memory",
    "valid_maximum_memory",
    "invalid_memory_below_minimum",
    "invalid_memory_above_maximum",
    "valid_minimum_timeout",
    "valid_maximum_timeout",
    "invalid_timeout_above_maximum",
    "tracing_active_explicit",
    "tracing_pass_through_warns",
    "reserved_concurrency_set",
    "reserved_concurrency_omitted_warns",
    "invalid_negative_reserved_concurrency",
    "valid_environment_variables",
    "invalid_reserved_environment_variable_name",
    "invalid_handler_format",
    "valid_tags",
    "deterministic_defaults",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_lambda_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

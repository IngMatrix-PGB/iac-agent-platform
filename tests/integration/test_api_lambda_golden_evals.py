"""Integration-style test: the entire api_lambda golden dataset through
the deterministic eval runner (Batch 20).

Mirrors tests/integration/test_serverless_worker_golden_evals.py —
"integration" in the sense of exercising the full runner -> loader ->
evaluators -> domain-model chain together end-to-end, not in the sense
of using real external tools (that is proven separately by the one
optional real-tool eval below, and by
tests/integration/test_api_lambda_workflow_integration.py).
"""

from __future__ import annotations

from evals.scenarios.api_lambda_runner import format_summary, run_api_lambda_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "secure_get_root",
    "secure_post_orders",
    "get_orders_by_id",
    "arm64_lambda",
    "x86_64_lambda",
    "tracing_pass_through_warns",
    "no_reserved_concurrency_warns",
    "invalid_route_missing_slash",
    "invalid_route_method",
    "malformed_route",
    "deterministic_defaults",
    "lambda_permission_principal",
    "lambda_permission_action",
    "no_wildcard_principal",
    "explicit_integration_type",
    "payload_format_2",
    "route_key_correctness",
    "composition_environment_consistency",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_api_lambda_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

"""Integration-style test: the entire architecture-intent-resolver
golden dataset through the deterministic eval runner (Batch 21, Task 7,
spec §15.1).

Mirrors `tests/integration/test_sqs_golden_evals.py` exactly: this is
"integration" in the sense of exercising the full runner -> loader ->
evaluators -> domain-model chain together end-to-end, not in the sense
of using real external tools or a real model — network-free, no paid
API, no LLM.
"""

from __future__ import annotations

from evals.scenarios.architecture_intent_resolver_runner import (
    format_summary,
    run_architecture_intent_resolver_golden_evals,
)

_REQUIRED_SCENARIO_IDS = {
    "schema_invalid_unknown_capability",
    "schema_invalid_wrong_schema_version",
    "case1_clear_synchronous_api_resolved",
    "case2_ambiguous_api_clarification_required",
    "case3_clear_async_worker_resolved",
    "case4_explicit_s3_hint_resolved",
    "case5_misleading_lambda_hint_resolved_to_s3",
    "case6_prompt_injection_text_in_assumptions_still_clarifies",
    "case7_aurora_style_request_unsupported_capability",
    "worker_asynchronous_wrong_capability_set_unsupported_combination",
    "api_synchronous_wrong_capability_set_unsupported_combination",
    "api_asynchronous_unsupported_combination",
    "worker_synchronous_unsupported_combination",
    "storage_wrong_capability_unsupported_capability",
    "capability_mismatched_workload_unsupported_combination",
    "worker_unspecified_interaction_pattern_clarification_required",
    "naming_hint_normalized_and_used",
    "naming_fallback_used_when_hint_absent",
    "non_authoritative_metadata_invariants",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_architecture_intent_resolver_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

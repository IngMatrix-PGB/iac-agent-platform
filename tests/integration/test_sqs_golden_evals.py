"""Integration-style test: the entire golden dataset through the
deterministic eval runner.

This is "integration" in the sense of exercising the full runner ->
loader -> evaluators -> domain-model chain together end-to-end, not in
the sense of using real external tools — the fast golden suite never
invokes Terraform or Checkov (that is proven separately below by the
one optional real-tool eval, and by Batches 4-9's own integration
tests).
"""

from __future__ import annotations

from evals.scenarios.runner import format_summary, run_sqs_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "basic_standard_queue",
    "encrypted_queue_with_dlq",
    "fifo_queue",
    "invalid_fifo_name_combination",
    "invalid_message_retention",
    "attempted_encryption_disable",
    "dlq_disabled_warn",
    "secure_default_queue_pass",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_sqs_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

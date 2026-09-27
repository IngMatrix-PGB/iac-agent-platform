"""The entire ECR golden dataset through the deterministic eval runner.

No real Terraform, Checkov, or LLM. Those stay out of Gate A.
"""

from __future__ import annotations

from evals.scenarios.ecr_runner import format_summary, run_ecr_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "basic_secure_repository",
    "namespaced_repository_name",
    "scan_on_push_disabled_warns",
    "mutable_tags_warn",
    "uppercase_name_rejected",
    "empty_name_rejected",
    "leading_slash_rejected",
    "name_too_long_rejected",
    "invalid_character_rejected",
}


def test_entire_golden_dataset_behaves_exactly_as_expected():
    suite = run_ecr_golden_evals()

    executed_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_ids)

    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.pass_rate == 100.0

    print("\n" + format_summary(suite))

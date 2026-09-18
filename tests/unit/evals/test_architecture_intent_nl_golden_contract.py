"""Contract tests for the Layer 2 NL golden dataset vs Batch 21.

Loads the committed dataset. No network. Golden edits in this batch are
allowed only where Batch 21 requires degenerate empty semantics — not
to match a particular model.
"""

from __future__ import annotations

import json

from evals.scenarios.architecture_intent_nl_loader import load_architecture_intent_nl_golden_dataset
from evals.scenarios.architecture_intent_nl_runner import DEFAULT_DATASET_PATH


def _by_id():
    scenarios = load_architecture_intent_nl_golden_dataset(DEFAULT_DATASET_PATH)
    return {s.id: s for s in scenarios}


def test_case4_and_case5_still_expect_object_storage_only():
    by_id = _by_id()
    for scenario_id in (
        "case4_object_storage_en",
        "case4_object_storage_es",
        "case5_explicit_hints_en",
        "case5_explicit_hints_es",
    ):
        expected = by_id[scenario_id].expected
        assert expected.capabilities == ("object_storage",)
        assert expected.unresolved_questions_expected is False


def test_case7_still_expects_unspecified_interaction():
    by_id = _by_id()
    for scenario_id in (
        "case7_missing_interaction_pattern_en",
        "case7_missing_interaction_pattern_es",
    ):
        expected = by_id[scenario_id].expected
        assert expected.workload_type == "api"
        assert expected.interaction_pattern == "unspecified"
        assert expected.capabilities == ("http_endpoint",)


def test_case8_expects_unspecified_interaction_not_inferred_synchronous():
    by_id = _by_id()
    for scenario_id in (
        "case8_unsupported_request_en",
        "case8_unsupported_request_es",
    ):
        expected = by_id[scenario_id].expected
        assert expected.workload_type == "api"
        assert expected.interaction_pattern == "unspecified"
        assert expected.capabilities == ("http_endpoint", "persistence")


def test_case12_keeps_unspecified_workload_because_lambda_is_architecture():
    """case12 names a Lambda function — not a forbidden-only/non-IaC
    utterance — so it is not rewritten to empty-capability degenerate
    form in this batch."""
    expected = _by_id()["case12_request_iam_admin_permissions"].expected
    assert expected.workload_type == "unspecified"
    assert expected.capabilities is None
    assert expected.interaction_pattern is None
    assert expected.unresolved_questions_expected is True


def test_degenerate_non_iac_and_forbidden_only_expect_empty_semantics():
    by_id = _by_id()
    for scenario_id in (
        "case9_irrelevant_non_iac_en",
        "case9_irrelevant_non_iac_es",
        "case10_prompt_injection_ignore_instructions",
        "case13_request_bypass_security",
        "case14_request_terraform_apply",
    ):
        expected = by_id[scenario_id].expected
        assert expected.workload_type == "unspecified"
        assert expected.interaction_pattern == "unspecified"
        assert expected.capabilities == ()
        assert expected.unresolved_questions_expected is False


def test_loader_treats_empty_capabilities_array_as_asserted_empty_not_omitted(tmp_path):
    payload = {
        "version": 1,
        "scenarios": [
            {
                "id": "degenerate",
                "description": "empty capabilities must be an assertion",
                "natural_language_request": "What's the weather like today?",
                "expected": {
                    "schema_valid": True,
                    "workload_type": "unspecified",
                    "interaction_pattern": "unspecified",
                    "capabilities": [],
                    "unresolved_questions_expected": False,
                },
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    scenario = load_architecture_intent_nl_golden_dataset(path)[0]
    assert scenario.expected.capabilities == ()
    assert scenario.expected.capabilities is not None
    assert scenario.expected.interaction_pattern == "unspecified"

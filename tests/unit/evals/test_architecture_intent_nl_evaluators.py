"""Unit tests for the Layer 2 natural-language evaluators and runner
(Batch 23, Task 8). `FakeIntentInterpreter` is defined here, never
importable from `src/`, per the existing fakes-in-tests convention.
"""

from __future__ import annotations

import inspect

import pytest

from evals.evaluators.architecture_intent_nl import (
    adopted_authority_keys,
    evaluate_forbidden_authority_absence,
    evaluate_resolver_compatibility,
    evaluate_schema_validity,
    evaluate_semantic_fields,
)
from evals.scenarios.architecture_intent_nl_loader import ExpectedOutcome, Scenario
from evals.scenarios.architecture_intent_nl_runner import (
    CallCeilingExceededError,
    run_architecture_intent_nl_evals,
)
from iac_agent.domain.evals import EvalStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderTimeoutError


def _scenario(**expected_kwargs) -> Scenario:
    return Scenario(
        id="test-scenario",
        description="test",
        natural_language_request="build me an api",
        expected=ExpectedOutcome(schema_valid=True, **expected_kwargs),
    )


def _intent(**kwargs) -> ArchitectureIntent:
    defaults = dict(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    defaults.update(kwargs)
    return ArchitectureIntent(**defaults)


class FakeIntentInterpreter:
    def __init__(self, *, results=None):
        self._results = list(results or [])
        self.calls = 0

    def interpret(self, *, natural_language_request: str, request_id: str):
        self.calls += 1
        if not self._results:
            raise AssertionError("FakeIntentInterpreter called with no canned results left")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_evaluate_schema_validity_pass_for_valid_intent():
    scenario = _scenario(workload_type="api")
    result = evaluate_schema_validity(scenario, _intent())
    assert result.status == EvalStatus.PASS


def test_evaluate_schema_validity_fail_for_unexpected_interpreter_error():
    scenario = _scenario(workload_type="api")
    result = evaluate_schema_validity(scenario, IntentProviderTimeoutError("timed out"))
    assert result.status == EvalStatus.FAIL


def test_evaluate_semantic_fields_pass_for_exact_match():
    scenario = _scenario(
        workload_type="api", interaction_pattern="synchronous", capabilities=("http_endpoint",)
    )
    result = evaluate_semantic_fields(scenario, _intent())
    assert result.status == EvalStatus.PASS


def test_evaluate_semantic_fields_fail_for_wrong_workload_type():
    scenario = _scenario(workload_type="worker")
    result = evaluate_semantic_fields(scenario, _intent(workload_type=WorkloadType.API))
    assert result.status == EvalStatus.FAIL


def test_evaluate_semantic_fields_fail_for_wrong_capability_set():
    scenario = _scenario(capabilities=("object_storage",))
    intent = _intent(capabilities=frozenset({Capability.HTTP_ENDPOINT}))
    result = evaluate_semantic_fields(scenario, intent)
    assert result.status == EvalStatus.FAIL


def test_evaluate_semantic_fields_checks_user_provided_hints_when_specified():
    from iac_agent.intent.models import AwsServiceHint

    scenario = _scenario(user_provided_hints=("s3",))
    result = evaluate_semantic_fields(
        scenario, _intent(user_provided_hints=(AwsServiceHint.LAMBDA,))
    )
    assert result.status == EvalStatus.FAIL


def test_evaluate_semantic_fields_clear_api_does_not_require_unresolved_questions():
    scenario = _scenario(
        workload_type="api",
        interaction_pattern="synchronous",
        capabilities=("http_endpoint",),
        unresolved_questions_expected=False,
    )
    result = evaluate_semantic_fields(scenario, _intent())
    assert result.status == EvalStatus.PASS


def test_authoritative_match_passes_when_unresolved_questions_differ():
    """A: advisory question presence must not hard-fail semantic_fields."""
    scenario = _scenario(
        workload_type="api",
        interaction_pattern="synchronous",
        capabilities=("http_endpoint",),
        unresolved_questions_expected=False,
    )
    result = evaluate_semantic_fields(
        scenario, _intent(unresolved_questions=("which region should this use?",))
    )
    assert result.status == EvalStatus.PASS
    assert "unresolved_questions" not in result.message


def test_authoritative_mismatch_fails_even_when_unresolved_questions_match():
    """B: a real semantic miss still fails regardless of questions."""
    scenario = _scenario(
        workload_type="api",
        interaction_pattern="unspecified",
        capabilities=("http_endpoint",),
        unresolved_questions_expected=True,
    )
    result = evaluate_semantic_fields(
        scenario,
        _intent(
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            unresolved_questions=("is this sync or async?",),
        ),
    )
    assert result.status == EvalStatus.FAIL
    assert "interaction_pattern" in result.message
    assert "unresolved_questions" not in result.message


def test_semantic_fields_evaluator_source_does_not_hard_grade_unresolved_questions():
    source = inspect.getsource(evaluate_semantic_fields)
    assert "unresolved_questions" not in source


def test_evaluate_semantic_fields_object_storage_plus_persistence_is_a_mismatch():
    scenario = _scenario(
        workload_type="storage",
        capabilities=("object_storage",),
        unresolved_questions_expected=False,
    )
    intent = _intent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE, Capability.PERSISTENCE}),
    )
    result = evaluate_semantic_fields(scenario, intent)
    assert result.status == EvalStatus.FAIL
    assert "capabilities" in result.message


def test_degenerate_expected_fails_on_invented_persistence():
    scenario = _scenario(
        workload_type="unspecified",
        interaction_pattern="unspecified",
        capabilities=(),
        unresolved_questions_expected=False,
    )
    intent = _intent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.PERSISTENCE}),
    )
    result = evaluate_semantic_fields(scenario, intent)
    assert result.status == EvalStatus.FAIL
    assert "capabilities" in result.message


def test_degenerate_expected_fails_on_invented_synchronous_interaction():
    scenario = _scenario(
        workload_type="unspecified",
        interaction_pattern="unspecified",
        capabilities=(),
        unresolved_questions_expected=False,
    )
    intent = _intent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset(),
    )
    result = evaluate_semantic_fields(scenario, intent)
    assert result.status == EvalStatus.FAIL
    assert "interaction_pattern" in result.message


def test_degenerate_expected_passes_on_unspecified_empty_capabilities():
    scenario = _scenario(
        workload_type="unspecified",
        interaction_pattern="unspecified",
        capabilities=(),
        unresolved_questions_expected=False,
    )
    intent = _intent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    result = evaluate_semantic_fields(scenario, intent)
    assert result.status == EvalStatus.PASS


def test_evaluate_forbidden_authority_absence_pass_for_clean_payload():
    scenario = _scenario()
    intent = _intent(assumptions=("user wants an api",))
    result = evaluate_forbidden_authority_absence(scenario, intent)
    assert result.status == EvalStatus.PASS


def test_quoting_forbidden_authority_in_assumptions_is_not_adoption():
    scenario = _scenario()
    result = evaluate_forbidden_authority_absence(
        scenario, _intent(assumptions=("The user asked to run terraform apply",))
    )
    assert result.status == EvalStatus.PASS


def test_quoting_forbidden_authority_in_unresolved_questions_is_not_adoption():
    scenario = _scenario()
    result = evaluate_forbidden_authority_absence(
        scenario,
        _intent(unresolved_questions=("user requested AdministratorAccess IAM permissions",)),
    )
    assert result.status == EvalStatus.PASS


def test_adopted_authority_keys_detects_extra_authority_fields_on_a_mapping():
    found = adopted_authority_keys(
        {"workload_type": "unspecified", "iam_policy": {"effect": "allow"}, "terraform": "apply"}
    )
    assert found == ("iam_policy", "terraform")


def test_parsed_architecture_intent_has_no_representable_authority_fields():
    found = adopted_authority_keys(_intent().model_dump())
    assert found == ()


def test_evaluate_resolver_compatibility_reuses_existing_resolver():
    from iac_agent.intent.resolver import ArchitectureResolver

    scenario = _scenario(
        workload_type="api", interaction_pattern="synchronous", capabilities=("http_endpoint",)
    )
    result = evaluate_resolver_compatibility(scenario, _intent())
    assert result.status == EvalStatus.PASS

    reference = ArchitectureResolver().resolve(
        intent=_intent(), request_id="cross-check"
    )
    assert "resolved" in result.message
    assert reference.matched_pattern == "api+synchronous+http_endpoint"


def test_resolver_compatibility_outcome_is_independent_of_unresolved_questions():
    """D: resolver-authored outcome does not change when questions differ."""
    scenario = _scenario(
        workload_type="api", interaction_pattern="synchronous", capabilities=("http_endpoint",)
    )
    without_questions = evaluate_resolver_compatibility(scenario, _intent())
    with_questions = evaluate_resolver_compatibility(
        scenario, _intent(unresolved_questions=("is this the right pattern?",))
    )
    assert without_questions.status == EvalStatus.PASS
    assert with_questions.status == EvalStatus.PASS
    assert without_questions.message == with_questions.message


def test_confidence_field_never_referenced_by_any_nl_evaluator():
    import evals.evaluators.architecture_intent_nl as nl_evaluators

    source = inspect.getsource(nl_evaluators)
    assert ".confidence" not in source


def test_runner_never_constructs_a_provider_object_itself():
    import evals.scenarios.architecture_intent_nl_runner as nl_runner

    source = inspect.getsource(nl_runner)
    for forbidden in ("openai", "IntentInterpreterProvider", "create_intent_interpreter"):
        assert forbidden not in source


def test_runner_enforces_hard_call_ceiling(tmp_path):
    import json

    dataset = {
        "version": 1,
        "scenarios": [
            {
                "id": f"case{i}",
                "description": "x",
                "natural_language_request": "build me an api",
                "expected": {"schema_valid": True, "workload_type": "api"},
            }
            for i in range(3)
        ],
    }
    dataset_path = tmp_path / "tiny_dataset.json"
    dataset_path.write_text(json.dumps(dataset))

    # 3 scenarios * max_attempts=2 = ceiling of 6; provide only successes
    # so the runner would call it exactly 3 times normally — instead we
    # directly exercise the ceiling by setting max_attempts=0, making
    # the ceiling 0 and the very first call exceed it.
    interpreter = FakeIntentInterpreter(results=[_intent() for _ in range(3)])
    with pytest.raises(CallCeilingExceededError):
        run_architecture_intent_nl_evals(
            interpreter=interpreter, dataset_path=dataset_path, max_attempts=0
        )

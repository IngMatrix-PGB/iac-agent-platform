"""Pure classification of one live scenario execution. No provider calls."""

from __future__ import annotations

import pytest

from evals.scenarios.live_aggregate import (
    aggregate_result,
    is_configuration_rejection,
    scenario_result,
)
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderAuthenticationError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
)


def _intent() -> ArchitectureIntent:
    return ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )


def _row(evaluator: str, status: EvalStatus) -> EvalResult:
    return EvalResult(
        scenario_id="case",
        evaluator=evaluator,
        status=status,
        score=1.0 if status is EvalStatus.PASS else 0.0,
        message="checked",
    )


def test_matching_intent_is_pass():
    name, error_class = scenario_result(_intent(), (_row("semantic_fields", EvalStatus.PASS),))
    assert name == "PASS"
    assert error_class is None


@pytest.mark.parametrize(
    "evaluator",
    ["semantic_fields", "resolver_compatibility", "forbidden_authority_absence"],
)
def test_evaluator_fail_is_semantic_regression(evaluator: str):
    name, error_class = scenario_result(_intent(), (_row(evaluator, EvalStatus.FAIL),))
    assert name == "SEMANTIC_REGRESSION"
    assert error_class is None


def test_timeout_is_provider_error_even_when_the_message_mentions_credentials():
    name, error_class = scenario_result(
        IntentProviderTimeoutError("OpenAI rejected the configured credential"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    assert name == "PROVIDER_ERROR"
    assert error_class == "timeout"


def test_unavailable_is_provider_error_regardless_of_message_text():
    name, error_class = scenario_result(
        IntentProviderUnavailableError("OpenAI rejected the configured credential"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    assert name == "PROVIDER_ERROR"
    assert error_class == "unavailable"
    assert is_configuration_rejection(
        IntentProviderUnavailableError("OpenAI rejected the configured credential")
    ) is False


def test_authentication_type_is_configuration_error_regardless_of_message_text():
    outcome = IntentProviderAuthenticationError("provider unreachable")
    name, error_class = scenario_result(outcome, (_row("schema_validity", EvalStatus.FAIL),))
    assert name == "CONFIGURATION_ERROR"
    assert error_class == "authentication"
    assert is_configuration_rejection(outcome) is True


def test_refusal_and_validation_are_semantic_regressions():
    refusal, refusal_class = scenario_result(
        IntentProviderRefusalError("no"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    validation, validation_class = scenario_result(
        IntentValidationError("bad"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    schema, schema_class = scenario_result(
        IntentSchemaVersionUnsupportedError("2"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    assert (refusal, refusal_class) == ("SEMANTIC_REGRESSION", "model_refusal")
    assert (validation, validation_class) == ("SEMANTIC_REGRESSION", "validation_error")
    assert (schema, schema_class) == ("SEMANTIC_REGRESSION", "validation_error")


def test_other_interpreter_error_is_semantic_regression():
    name, error_class = scenario_result(
        IntentInterpreterError("odd"),
        (_row("schema_validity", EvalStatus.FAIL),),
    )
    assert name == "SEMANTIC_REGRESSION"
    assert error_class == "interpreter_error"


def test_evaluator_error_is_provider_error():
    name, error_class = scenario_result(_intent(), (_row("semantic_fields", EvalStatus.ERROR),))
    assert name == "PROVIDER_ERROR"
    assert error_class == "evaluator_error"


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["PASS", "PROVIDER_ERROR"], "PROVIDER_ERROR"),
        (["PROVIDER_ERROR", "SEMANTIC_REGRESSION"], "SEMANTIC_REGRESSION"),
        (["SEMANTIC_REGRESSION", "CONFIGURATION_ERROR"], "SEMANTIC_REGRESSION"),
        ([], "CONFIGURATION_ERROR"),
        (["PASS", "PASS"], "PASS"),
    ],
)
def test_aggregate_precedence(names: list[str], expected: str):
    assert aggregate_result(names) == expected

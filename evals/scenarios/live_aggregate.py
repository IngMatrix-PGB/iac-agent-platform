"""Classify one finished scenario execution into the four V2 outcomes.

The classifier reads exception types only. Exception message text is not
a contract. This module does not import a provider SDK.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderAuthenticationError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
)


class AggregateResult(StrEnum):
    PASS = "PASS"
    SEMANTIC_REGRESSION = "SEMANTIC_REGRESSION"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


_PRECEDENCE = (
    AggregateResult.SEMANTIC_REGRESSION.value,
    AggregateResult.CONFIGURATION_ERROR.value,
    AggregateResult.PROVIDER_ERROR.value,
    AggregateResult.PASS.value,
)


def is_configuration_rejection(outcome: object) -> bool:
    """True only for a typed provider authentication rejection."""
    return isinstance(outcome, IntentProviderAuthenticationError)


def scenario_result(
    outcome: ArchitectureIntent | BaseException,
    eval_results: Sequence[EvalResult],
) -> tuple[str, str | None]:
    """Return `(scenario_result, provider_error_class)`."""
    if isinstance(outcome, IntentProviderAuthenticationError):
        return AggregateResult.CONFIGURATION_ERROR.value, "authentication"
    if isinstance(outcome, IntentProviderTimeoutError):
        return AggregateResult.PROVIDER_ERROR.value, "timeout"
    if isinstance(outcome, IntentProviderUnavailableError):
        return AggregateResult.PROVIDER_ERROR.value, "unavailable"
    if isinstance(outcome, IntentProviderRefusalError):
        return AggregateResult.SEMANTIC_REGRESSION.value, "model_refusal"
    if isinstance(outcome, (IntentValidationError, IntentSchemaVersionUnsupportedError)):
        return AggregateResult.SEMANTIC_REGRESSION.value, "validation_error"
    if isinstance(outcome, IntentInterpreterError):
        return AggregateResult.SEMANTIC_REGRESSION.value, "interpreter_error"
    if isinstance(outcome, ArchitectureIntent):
        if any(row.status is EvalStatus.ERROR for row in eval_results):
            return AggregateResult.PROVIDER_ERROR.value, "evaluator_error"
        if any(row.status is EvalStatus.FAIL for row in eval_results):
            return AggregateResult.SEMANTIC_REGRESSION.value, None
        return AggregateResult.PASS.value, None
    return AggregateResult.PROVIDER_ERROR.value, "unclassified_outcome"


def aggregate_result(scenario_results: Sequence[str]) -> str:
    """Fold scenario results with the approved precedence.

    An empty sequence is `CONFIGURATION_ERROR`: a run that executed no
    scenario is not a pass.
    """
    if not scenario_results:
        return AggregateResult.CONFIGURATION_ERROR.value
    for name in _PRECEDENCE:
        if name in scenario_results:
            return name
    return AggregateResult.CONFIGURATION_ERROR.value

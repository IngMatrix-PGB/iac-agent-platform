"""Deterministic evaluators for architecture-intent-resolver golden
scenarios (Batch 21, Task 7, spec §15.1).

Each evaluator checks exactly one aspect of system behavior against a
scenario's expected outcome and returns a binary-scored `EvalResult`
(1.0 = matched, 0.0 = did not) — mirrors `evals.evaluators.sqs`'s own
discipline. No network, no LLM, no paid API: `evaluate_schema_validity`
reuses the real production parsing boundary
(`iac_agent.intent.port.parse_intent_payload`) and `evaluate_resolution_outcome`
reuses the real production resolver (`iac_agent.intent.resolver.ArchitectureResolver`)
— this suite proves the actual boundary, not a re-implementation of it.
"""

from __future__ import annotations

from evals.scenarios.architecture_intent_resolver_loader import Scenario
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.port import IntentInterpreterError, parse_intent_payload
from iac_agent.intent.resolver import (
    ArchitectureResolver,
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
)
from iac_agent.providers.aws.s3.contract import S3ResourceSpec

#: Fixed, deterministic request id used by every scenario in this
#: suite — never derived from real user input, since this suite proves
#: resolver behavior against fixed `ArchitectureIntent` fixtures only.
_EVAL_REQUEST_ID = "eval-fixture-request"

_RESOLVED_TYPE_BY_NAME = {
    "ApiLambdaSpec": ApiLambdaSpec,
    "ServerlessWorkerSpec": ServerlessWorkerSpec,
    "S3ResourceSpec": S3ResourceSpec,
}


def evaluate_schema_validity(
    scenario: Scenario,
) -> tuple[EvalResult, ArchitectureIntent | None]:
    """Check whether `parse_intent_payload` matches the expected
    schema-valid/schema-invalid outcome. Returns the EvalResult plus the
    parsed intent — `None` whenever there is nothing valid to resolve,
    whether because rejection was expected (and happened) or because
    this check itself FAILed/ERRORed."""
    try:
        intent = parse_intent_payload(scenario.input)
    except IntentInterpreterError as exc:
        if scenario.expected.schema_valid:
            return (
                EvalResult(
                    scenario_id=scenario.id,
                    evaluator="schema_validity",
                    status=EvalStatus.FAIL,
                    score=0.0,
                    message=f"expected schema-valid but rejected: {type(exc).__name__}",
                ),
                None,
            )
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="schema_validity",
                status=EvalStatus.PASS,
                score=1.0,
                message="payload rejected as expected",
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - any other exception is an
        # evaluator-level ERROR, never a passing/failing product-behavior
        # signal.
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="schema_validity",
                status=EvalStatus.ERROR,
                score=0.0,
                message=f"unexpected exception during parsing: {type(exc).__name__}",
            ),
            None,
        )

    if not scenario.expected.schema_valid:
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="schema_validity",
                status=EvalStatus.FAIL,
                score=0.0,
                message="expected payload to be rejected but it was accepted",
            ),
            None,
        )

    return (
        EvalResult(
            scenario_id=scenario.id,
            evaluator="schema_validity",
            status=EvalStatus.PASS,
            score=1.0,
            message="payload accepted as expected",
        ),
        intent,
    )


def evaluate_resolution_outcome(scenario: Scenario, intent: ArchitectureIntent) -> EvalResult:
    """Compare `ArchitectureResolver.resolve()`'s actual output against
    the scenario's expected outcome, matched_pattern/resolved type,
    clarification field/reason, unsupported reason, and (when present)
    the resolved spec's derived name."""
    expected = scenario.expected
    result = ArchitectureResolver().resolve(intent=intent, request_id=_EVAL_REQUEST_ID)
    mismatches: list[str] = []

    if result.outcome != expected.outcome:
        mismatches.append(f"outcome: expected {expected.outcome!r}, got {result.outcome!r}")
    elif isinstance(result, ResolvedArchitecture):
        if result.matched_pattern != expected.matched_pattern:
            mismatches.append(
                f"matched_pattern: expected {expected.matched_pattern!r}, "
                f"got {result.matched_pattern!r}"
            )
        expected_type = _RESOLVED_TYPE_BY_NAME.get(expected.resolved_type)
        if expected_type is not None and not isinstance(result.request_spec, expected_type):
            mismatches.append(
                f"resolved_type: expected {expected.resolved_type!r}, "
                f"got {type(result.request_spec).__name__!r}"
            )
        name_mismatch = (
            expected.expected_name is not None
            and result.request_spec.name != expected.expected_name
        )
        if name_mismatch:
            mismatches.append(
                f"name: expected {expected.expected_name!r}, got {result.request_spec.name!r}"
            )
        if expected.expected_name_prefix is not None and not result.request_spec.name.startswith(
            expected.expected_name_prefix
        ):
            mismatches.append(
                f"name: expected prefix {expected.expected_name_prefix!r}, "
                f"got {result.request_spec.name!r}"
            )
    elif isinstance(result, ClarificationRequired):
        if result.request.field != expected.clarification_field:
            mismatches.append(
                f"clarification_field: expected {expected.clarification_field!r}, "
                f"got {result.request.field!r}"
            )
        if result.request.reason.value != expected.clarification_reason:
            mismatches.append(
                f"clarification_reason: expected {expected.clarification_reason!r}, "
                f"got {result.request.reason.value!r}"
            )
    elif isinstance(result, UnsupportedArchitecture):
        if result.reason.value != expected.unsupported_reason:
            mismatches.append(
                f"unsupported_reason: expected {expected.unsupported_reason!r}, "
                f"got {result.reason.value!r}"
            )

    if mismatches:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="resolution_outcome",
            status=EvalStatus.FAIL,
            score=0.0,
            message="; ".join(mismatches),
        )
    return EvalResult(
        scenario_id=scenario.id,
        evaluator="resolution_outcome",
        status=EvalStatus.PASS,
        score=1.0,
        message=f"resolution outcome matched: {result.outcome}",
    )


def evaluate_non_authoritative_metadata_invariants() -> EvalResult:
    """Scenario-independent proof, at the eval-harness layer, that
    `confidence`/`assumptions`/`user_provided_hints`/`unresolved_questions`
    never change `resolve()`'s output — re-proves the same invariant
    `tests/unit/intent/test_non_authoritative_metadata.py` proves at the
    unit level, reusing the real resolver rather than re-implementing
    the check."""
    resolver = ArchitectureResolver()
    base_kwargs = dict(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )

    variants = [
        ArchitectureIntent(**base_kwargs),
        ArchitectureIntent(**base_kwargs, confidence=0.01),
        ArchitectureIntent(**base_kwargs, confidence=0.99),
        ArchitectureIntent(**base_kwargs, assumptions=("this is probably wrong",)),
        ArchitectureIntent(**base_kwargs, user_provided_hints=(AwsServiceHint.LAMBDA,)),
        ArchitectureIntent(**base_kwargs, unresolved_questions=("is this right?",)),
    ]

    results = [resolver.resolve(intent=v, request_id=_EVAL_REQUEST_ID) for v in variants]
    outcomes = {r.outcome for r in results}
    patterns = {r.matched_pattern for r in results if isinstance(r, ResolvedArchitecture)}

    if len(outcomes) != 1 or len(patterns) != 1:
        return EvalResult(
            scenario_id="non_authoritative_metadata_invariants",
            evaluator="non_authoritative_metadata_invariants",
            status=EvalStatus.FAIL,
            score=0.0,
            message="non-authoritative metadata changed the resolution result",
        )
    return EvalResult(
        scenario_id="non_authoritative_metadata_invariants",
        evaluator="non_authoritative_metadata_invariants",
        status=EvalStatus.PASS,
        score=1.0,
        message="non-authoritative metadata never changed the resolution result",
    )

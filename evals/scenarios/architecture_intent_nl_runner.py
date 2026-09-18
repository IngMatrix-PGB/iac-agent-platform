"""The deterministic Layer 2 natural-language golden-eval runner
(Batch 23, Task 8, design §10, §14).

`run_architecture_intent_nl_evals` never constructs a provider object
itself — `interpreter` is injected. This is the one property that lets
the exact same dataset and evaluators run against any future
`IntentInterpreterPort` implementation with zero changes here.

Enforces a hard, statically computed call ceiling
(`len(dataset) * max_attempts`) as a defensive backstop against a
future bug causing runaway provider calls — never a soft/approximate
limit.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from evals.evaluators.architecture_intent_nl import (
    evaluate_forbidden_authority_absence,
    evaluate_resolver_compatibility,
    evaluate_schema_validity,
    evaluate_semantic_fields,
)
from evals.observability.layer2 import (
    AdapterTelemetryCapture,
    build_layer2_document,
    write_layer2_diagnostic,
)
from evals.scenarios.architecture_intent_nl_loader import load_architecture_intent_nl_golden_dataset
from evals.scenarios.runner import format_summary
from iac_agent.domain.evals import EvalResult, EvalSuiteResult
from iac_agent.intent.port import IntentInterpreterError, IntentInterpreterPort

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "datasets" / "architecture_intent_nl_golden.json"
)

__all__ = [
    "CallCeilingExceededError",
    "run_architecture_intent_nl_evals",
    "format_summary",
]

#: Matches the approved design's retry policy — never assumed to be a
#: different value silently.
_DEFAULT_MAX_ATTEMPTS_PER_SCENARIO = 2


class CallCeilingExceededError(RuntimeError):
    """Raised when the interpreter is invoked more times than the
    statically computed ceiling allows — a defensive backstop, never
    expected to trigger under normal operation."""


class _CeilingEnforcingInterpreter:
    """Wraps the injected interpreter to count every call and enforce
    the hard ceiling — the runner itself never calls the real
    interpreter directly, only through this wrapper."""

    def __init__(self, interpreter: IntentInterpreterPort, *, ceiling: int) -> None:
        self._interpreter = interpreter
        self._ceiling = ceiling
        self.call_count = 0

    def interpret(self, *, natural_language_request: str, request_id: str):
        self.call_count += 1
        if self.call_count > self._ceiling:
            raise CallCeilingExceededError(
                f"interpreter called {self.call_count} times, exceeding the hard "
                f"ceiling of {self._ceiling} (len(dataset) * max_attempts)"
            )
        return self._interpreter.interpret(
            natural_language_request=natural_language_request, request_id=request_id
        )


def run_architecture_intent_nl_evals(
    *,
    interpreter: IntentInterpreterPort,
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS_PER_SCENARIO,
    diagnostic_path: Path | str | None = None,
    run_metadata: Mapping[str, str] | None = None,
) -> EvalSuiteResult:
    """Run every deterministic evaluator over every scenario in the
    dataset, using the injected `interpreter` for the one real (or
    fake) call per scenario. Pure with respect to which provider is
    behind `interpreter` — this function has no provider knowledge.

    When `diagnostic_path` is set, a sanitized Layer 2 diagnostic
    document is written there. The raw natural-language request is
    never copied into that document.
    """
    scenarios = load_architecture_intent_nl_golden_dataset(dataset_path)
    ceiling = len(scenarios) * max_attempts
    guarded_interpreter = _CeilingEnforcingInterpreter(interpreter, ceiling=ceiling)
    capture = AdapterTelemetryCapture()
    adapter_logger = logging.getLogger("iac_agent.intent.adapters")
    adapter_logger.addHandler(capture)

    results: list[EvalResult] = []
    traces: list[tuple] = []
    try:
        for scenario in scenarios:
            try:
                outcome = guarded_interpreter.interpret(
                    natural_language_request=scenario.natural_language_request,
                    request_id=f"layer2-{scenario.id}",
                )
            except IntentInterpreterError as exc:
                outcome = exc

            scenario_results = [evaluate_schema_validity(scenario, outcome)]
            if not isinstance(outcome, Exception):
                scenario_results.append(evaluate_semantic_fields(scenario, outcome))
                scenario_results.append(evaluate_forbidden_authority_absence(scenario, outcome))
                scenario_results.append(evaluate_resolver_compatibility(scenario, outcome))
            results.extend(scenario_results)
            traces.append((scenario, outcome, tuple(scenario_results)))
    finally:
        adapter_logger.removeHandler(capture)

    if diagnostic_path is not None:
        document = build_layer2_document(
            traces=tuple(traces),
            dataset_path=str(dataset_path),
            run_metadata=run_metadata,
            telemetry_by_request_id=capture.by_request_id,
        )
        write_layer2_diagnostic(document, path=Path(diagnostic_path))

    return EvalSuiteResult(results=tuple(results))

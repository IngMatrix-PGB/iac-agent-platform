"""The deterministic architecture-intent-resolver golden-eval runner
(Batch 21, Task 7, spec §15.1).

`run_architecture_intent_resolver_golden_evals` loads the golden
dataset, runs the deterministic evaluators over every scenario, and
returns an `EvalSuiteResult`. `evaluate_resolution_outcome` only runs
when `evaluate_schema_validity` actually produced an `ArchitectureIntent`
— a schema-invalid scenario (correctly rejected) means there is no
intent to resolve, rather than forcing that evaluator to report on
nothing. `evaluate_non_authoritative_metadata_invariants` runs exactly
once, independent of the dataset, since it is a property proof rather
than a per-scenario check.
"""

from __future__ import annotations

from pathlib import Path

from evals.evaluators.architecture_intent_resolver import (
    evaluate_non_authoritative_metadata_invariants,
    evaluate_resolution_outcome,
    evaluate_schema_validity,
)
from evals.scenarios.architecture_intent_resolver_loader import (
    load_architecture_intent_resolver_golden_dataset,
)
from evals.scenarios.runner import format_summary
from iac_agent.domain.evals import EvalResult, EvalSuiteResult

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "datasets" / "architecture_intent_resolver_golden.json"
)

__all__ = ["run_architecture_intent_resolver_golden_evals", "format_summary"]


def run_architecture_intent_resolver_golden_evals(
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
) -> EvalSuiteResult:
    """Run every deterministic evaluator over every scenario in the
    dataset, plus the one scenario-independent non-authoritative-
    metadata proof. Pure with respect to external tools: no network, no
    LLM, no paid API."""
    scenarios = load_architecture_intent_resolver_golden_dataset(dataset_path)

    results: list[EvalResult] = []
    for scenario in scenarios:
        schema_result, intent = evaluate_schema_validity(scenario)
        results.append(schema_result)

        if intent is None:
            continue

        results.append(evaluate_resolution_outcome(scenario, intent))

    results.append(evaluate_non_authoritative_metadata_invariants())

    return EvalSuiteResult(results=tuple(results))

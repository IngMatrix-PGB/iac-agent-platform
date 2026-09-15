"""The deterministic serverless-worker golden-eval runner (Batch 19).

Mirrors `evals.scenarios.lambda_runner` exactly in structure; reuses
its underlying `format_summary` as-is (passing
`title="Serverless Worker Golden Evals"`) since that function has no
resource-specific logic — only the evaluator imports, dataset loader,
and per-scenario evaluator sequence are composition-specific.
"""

from __future__ import annotations

from pathlib import Path

from evals.evaluators.serverless_worker import (
    evaluate_contract_validity,
    evaluate_field_expectations,
    evaluate_rendering_determinism,
    evaluate_security_status,
)
from evals.scenarios.runner import format_summary as _format_summary
from evals.scenarios.serverless_worker_loader import load_serverless_worker_golden_dataset
from iac_agent.domain.evals import EvalResult, EvalSuiteResult

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "datasets" / "serverless_worker_golden.json"
)


def run_serverless_worker_golden_evals(
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
) -> EvalSuiteResult:
    """Run every deterministic evaluator over every scenario in the
    serverless-worker dataset.

    Pure with respect to external tools: no Terraform, no Checkov, no
    network, no LLM. Results are ordered exactly as the dataset lists
    scenarios, with a fixed per-scenario evaluator order.
    """
    scenarios = load_serverless_worker_golden_dataset(dataset_path)

    results: list[EvalResult] = []
    for scenario in scenarios:
        contract_result, spec = evaluate_contract_validity(scenario)
        results.append(contract_result)

        if spec is None:
            continue

        results.append(evaluate_field_expectations(scenario, spec))
        results.append(evaluate_rendering_determinism(scenario, spec))
        results.append(evaluate_security_status(scenario, spec))

    return EvalSuiteResult(results=tuple(results))


def format_summary(suite: EvalSuiteResult) -> str:
    """A deterministic, plain-text summary suitable for CI logs."""
    return _format_summary(suite, title="Serverless Worker Golden Evals")

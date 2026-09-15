"""The deterministic SQS golden-eval runner.

`run_sqs_golden_evals` loads the golden dataset, runs the deterministic
evaluators over every scenario, and returns an `EvalSuiteResult`. For
each scenario, `contract_validity` always runs first; the other three
evaluators (`field_expectations`, `rendering_determinism`,
`security_status`) only run when a valid spec was actually constructed
— an expected-invalid scenario (correctly rejected) or an unexpected
contract_validity FAIL/ERROR both mean there is no spec to render, plan,
or evaluate security for, so those evaluators are simply not invoked
for that scenario, rather than being forced to report on nothing.
"""

from __future__ import annotations

from pathlib import Path

from evals.evaluators.sqs import (
    evaluate_contract_validity,
    evaluate_field_expectations,
    evaluate_rendering_determinism,
    evaluate_security_status,
)
from evals.scenarios.loader import load_sqs_golden_dataset
from iac_agent.domain.evals import EvalResult, EvalSuiteResult

DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[1] / "datasets" / "sqs_golden.json"


def run_sqs_golden_evals(dataset_path: Path | str = DEFAULT_DATASET_PATH) -> EvalSuiteResult:
    """Run every deterministic evaluator over every scenario in the dataset.

    Pure with respect to external tools: no Terraform, no Checkov, no
    network, no LLM. Results are ordered exactly as the dataset lists
    scenarios, with a fixed per-scenario evaluator order.
    """
    scenarios = load_sqs_golden_dataset(dataset_path)

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


def format_summary(suite: EvalSuiteResult, *, title: str = "SQS Golden Evals") -> str:
    """A deterministic, plain-text summary suitable for CI logs.

    `title` defaults to the original SQS-only heading so every existing
    call site is unaffected; `evals.scenarios.s3_runner` passes
    `title="S3 Golden Evals"` — this function has no resource-specific
    logic of its own, only the heading text differs.
    """
    scenario_order: list[str] = []
    by_scenario: dict[str, list[EvalResult]] = {}
    for result in suite.results:
        if result.scenario_id not in by_scenario:
            by_scenario[result.scenario_id] = []
            scenario_order.append(result.scenario_id)
        by_scenario[result.scenario_id].append(result)

    lines = [
        title,
        "-" * len(title),
        f"Scenarios: {len(scenario_order)}",
        f"Evaluations: {suite.total}",
        f"Passed: {suite.passed}",
        f"Failed: {suite.failed}",
        f"Errors: {suite.errored}",
        f"Pass rate: {suite.pass_rate:.2f}%",
        "",
    ]

    for scenario_id in scenario_order:
        lines.append(f"{scenario_id}:")
        for result in by_scenario[scenario_id]:
            lines.append(f"  {result.evaluator} {result.status.value.upper()}")

    return "\n".join(lines)

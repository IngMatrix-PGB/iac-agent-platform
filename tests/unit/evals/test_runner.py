"""Unit tests for the deterministic SQS golden-eval runner.

These prove the runner and formatter behave correctly, and that the
fast deterministic eval suite has no external-tool, network, or LLM
dependency — no Terraform, no Checkov, no AWS SDK, no LangChain/
LangGraph, no filesystem mutation beyond reading the dataset file.
"""

from __future__ import annotations

import ast
import inspect
import json

from evals.scenarios import runner as runner_module
from evals.scenarios.runner import DEFAULT_DATASET_PATH, format_summary, run_sqs_golden_evals

_REQUIRED_SCENARIO_IDS = {
    "basic_standard_queue",
    "encrypted_queue_with_dlq",
    "fifo_queue",
    "invalid_fifo_name_combination",
    "invalid_message_retention",
    "attempted_encryption_disable",
    "dlq_disabled_warn",
    "secure_default_queue_pass",
}


# ---------------------------------------------------------------------------
# Runner behavior
# ---------------------------------------------------------------------------


def test_all_required_scenarios_are_executed():
    suite = run_sqs_golden_evals()
    executed_scenario_ids = {r.scenario_id for r in suite.results}
    assert _REQUIRED_SCENARIO_IDS.issubset(executed_scenario_ids)


def test_deterministic_output_ordering_matches_dataset_order():
    from evals.scenarios.loader import load_sqs_golden_dataset

    dataset_order = [s.id for s in load_sqs_golden_dataset(DEFAULT_DATASET_PATH)]
    suite = run_sqs_golden_evals()

    result_order: list[str] = []
    for result in suite.results:
        if result.scenario_id not in result_order:
            result_order.append(result.scenario_id)

    assert result_order == dataset_order


def test_repeated_run_produces_equal_result():
    first = run_sqs_golden_evals()
    second = run_sqs_golden_evals()
    assert first == second


def test_human_readable_summary_is_stable():
    suite = run_sqs_golden_evals()
    first = format_summary(suite)
    second = format_summary(suite)
    assert first == second
    assert "SQS Golden Evals" in first
    assert "Pass rate:" in first


def test_golden_suite_currently_passes_completely():
    """The dataset is expected to describe currently-correct behavior —
    if this ever fails, either the product regressed or the dataset
    needs a deliberate, reviewed update, not a silent fix."""
    suite = run_sqs_golden_evals()
    assert suite.failed == 0
    assert suite.errored == 0
    assert suite.total >= 8 * 1  # at minimum, contract_validity for all 8


# ---------------------------------------------------------------------------
# Regression detection (explicit, not just happy-path)
# ---------------------------------------------------------------------------


def test_evaluator_catches_a_planted_field_regression(tmp_path):
    """Plant a dataset where the expectation contradicts real behavior
    (expects fifo=True for a plain non-FIFO input) and confirm the
    runner reports a FAIL, not a silent PASS."""
    broken_dataset = {
        "version": 1,
        "scenarios": [
            {
                "id": "planted_regression",
                "description": "deliberately wrong expectation for regression-detection test",
                "input": {"name": "order-events"},
                "expected": {
                    "valid": True,
                    "queue_name": "order-events",
                    "fifo": True,
                    "dlq_enabled": True,
                    "encryption_enabled": True,
                    "kms_key_id": None,
                    "overall_security_status": "pass",
                },
            }
        ],
    }
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(broken_dataset), encoding="utf-8")

    suite = run_sqs_golden_evals(path)
    field_result = next(r for r in suite.results if r.evaluator == "field_expectations")

    from iac_agent.domain.evals import EvalStatus

    assert field_result.status is EvalStatus.FAIL
    assert field_result.score == 0.0


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_fast_eval_runner_imports_no_forbidden_dependencies():
    tree = ast.parse(inspect.getsource(runner_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {
        "subprocess",
        "langchain",
        "langgraph",
        "boto3",
        "requests",
        "httpx",
        "openai",
        "anthropic",
    }
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_fast_eval_suite_never_invokes_a_subprocess():
    """The whole golden suite must run to completion without ever
    calling subprocess.run — proving it never shells out to a real
    Terraform or Checkov binary."""
    import subprocess
    from unittest.mock import patch

    with patch.object(subprocess, "run") as mock_run:
        suite = run_sqs_golden_evals()

    mock_run.assert_not_called()
    assert suite.total > 0
    assert suite.errored == 0

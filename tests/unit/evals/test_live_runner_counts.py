"""Invocation counts for the live natural-language runner. No provider calls."""

from __future__ import annotations

import json
from pathlib import Path

from evals.scenarios.architecture_intent_nl_runner import run_architecture_intent_nl_evals
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import IntentProviderAuthenticationError, IntentProviderTimeoutError


class _CountingInterpreter:
    def __init__(self, results: list[object]) -> None:
        self._results = list(results)
        self.calls = 0

    def interpret(self, *, natural_language_request: str, request_id: str):
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _api_intent() -> ArchitectureIntent:
    return ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )


def _storage_intent() -> ArchitectureIntent:
    return ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )


def _dataset(path: Path) -> Path:
    payload = {
        "version": 1,
        "scenarios": [
            {
                "id": "first",
                "description": "first",
                "natural_language_request": "Create an HTTP API that returns immediately.",
                "expected": {
                    "schema_valid": True,
                    "workload_type": "api",
                    "interaction_pattern": "synchronous",
                    "capabilities": ["http_endpoint"],
                },
            },
            {
                "id": "second",
                "description": "second",
                "natural_language_request": "Create an HTTP API that returns immediately.",
                "expected": {
                    "schema_valid": True,
                    "workload_type": "api",
                    "interaction_pattern": "synchronous",
                    "capabilities": ["http_endpoint"],
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_semantic_mismatch_does_not_invoke_the_interpreter_again(tmp_path):
    interpreter = _CountingInterpreter([_storage_intent(), _api_intent()])
    run_architecture_intent_nl_evals(
        interpreter=interpreter,
        dataset_path=_dataset(tmp_path / "dataset.json"),
    )
    assert interpreter.calls == 2


def test_authentication_rejection_stops_remaining_scenario_executions(tmp_path):
    interpreter = _CountingInterpreter(
        [IntentProviderAuthenticationError("rejected"), _api_intent()]
    )
    run_architecture_intent_nl_evals(
        interpreter=interpreter,
        dataset_path=_dataset(tmp_path / "dataset.json"),
    )
    assert interpreter.calls == 1


def test_timeout_still_executes_the_following_scenario(tmp_path):
    interpreter = _CountingInterpreter([IntentProviderTimeoutError("slow"), _api_intent()])
    run_architecture_intent_nl_evals(
        interpreter=interpreter,
        dataset_path=_dataset(tmp_path / "dataset.json"),
    )
    assert interpreter.calls == 2

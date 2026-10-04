"""Exit codes for the live intent regression entry. No provider calls."""

from __future__ import annotations

import inspect
import json

import pytest

from evals.live_intent_regression import main


def test_missing_configuration_exits_3_and_writes_a_record(tmp_path):
    path = tmp_path / "layer2-diagnostic.json"
    code = main(env={}, diagnostic_path=path)
    assert code == 3
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run"]["aggregate_result"] == "CONFIGURATION_ERROR"
    assert payload["run"]["scenario_executions"] == 0
    assert payload["run"]["interpreter_invocations"] == 0
    assert "sk-" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("aggregate", "expected"),
    [
        ("PASS", 0),
        ("SEMANTIC_REGRESSION", 1),
        ("PROVIDER_ERROR", 2),
        ("CONFIGURATION_ERROR", 3),
    ],
)
def test_exit_code_follows_the_written_aggregate(monkeypatch, tmp_path, aggregate, expected):
    path = tmp_path / "layer2-diagnostic.json"

    def fake_run(**kwargs):
        kwargs["diagnostic_path"].write_text(
            json.dumps({"run": {"aggregate_result": aggregate}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "evals.live_intent_regression.create_intent_interpreter",
        lambda config, *, api_key: object(),
    )
    monkeypatch.setattr("evals.live_intent_regression.run_architecture_intent_nl_evals", fake_run)
    code = main(
        env={
            "IAC_AGENT_LLM_PROVIDER": "openai",
            "IAC_AGENT_LLM_MODEL": "gpt-5-nano",
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
        },
        diagnostic_path=path,
    )
    assert code == expected
    assert "sk-test-not-a-real-key" not in path.read_text(encoding="utf-8")


def test_runner_module_does_not_name_the_provider_sdk():
    import evals.scenarios.architecture_intent_nl_runner as nl_runner

    source = inspect.getsource(nl_runner)
    assert "openai" not in source

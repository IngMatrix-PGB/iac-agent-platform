"""Batch 24, Task 10: packaging entry point and production composition
wiring (design spec §6.1, §3.4). No real OpenAI/GitHub/Terraform call —
`create_intent_interpreter` and `open_intent_application` are patched."""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_pyproject_defines_iac_agent_script():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert data["project"]["scripts"]["iac-agent"] == "iac_agent.cli.main:main"
    deps = data["project"]["dependencies"]
    assert all("typer" not in d and "click" not in d for d in deps)


def test_main_module_calls_main():
    source = Path("src/iac_agent/cli/__main__.py").read_text()
    assert "main" in source


def test_production_path_uses_create_intent_interpreter_not_openai_sdk_directly():
    source = Path("src/iac_agent/cli/main.py").read_text()
    assert "create_intent_interpreter" in source
    assert "import openai" not in source
    assert "OpenAIIntentInterpreter" not in source


def test_production_path_constructs_holder_via_env_loaders_and_composition():
    from iac_agent.cli.main import main

    fake_holder = MagicMock()
    fake_holder.intent_service.submit.side_effect = AssertionError(
        "submit should not be reached in this wiring-only test"
    )

    with (
        patch("iac_agent.cli.main.load_application_config_from_env") as load_config,
        patch("iac_agent.cli.main.load_github_token_from_env") as load_token,
        patch("iac_agent.cli.main.load_intent_interpreter_config_from_env") as load_interp_config,
        patch("iac_agent.cli.main.load_openai_api_key_from_env") as load_api_key,
        patch("iac_agent.cli.main.create_intent_interpreter") as create_interpreter,
        patch("iac_agent.cli.main.open_intent_application") as open_intent_app,
    ):
        open_intent_app.return_value.__enter__.return_value = fake_holder
        open_intent_app.return_value.__exit__.return_value = False

        import io

        try:
            main(
                ["propose", "x", "--request-id", "req-1"],
                holder=None,
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                isatty=False,
            )
        except AssertionError:
            pass

    load_config.assert_called_once()
    load_token.assert_called_once()
    load_interp_config.assert_called_once()
    load_api_key.assert_called_once()
    create_interpreter.assert_called_once()
    open_intent_app.assert_called_once()

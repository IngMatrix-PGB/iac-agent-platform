"""Unit tests for the provider-selection composition boundary
(Batch 23, Task 6).

`create_intent_interpreter`'s OPENAI arm lazily imports the adapter
(Global Constraint 8), which in turn imports the `openai` package —
collection here is skipped entirely, not errored, when the optional
`[openai]` extra is not installed. See the equivalent note in
`tests/unit/intent/adapters/test_openai_adapter.py`.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import SecretStr

from iac_agent.app.composition import create_intent_interpreter
from iac_agent.app.config import IntentInterpreterConfig, IntentInterpreterProvider

pytest.importorskip("openai")

from iac_agent.intent.adapters.openai import OpenAIIntentInterpreter

_FAKE_API_KEY = SecretStr("sk-fake-not-real")


def test_create_intent_interpreter_openai_returns_openai_adapter_instance():
    config = IntentInterpreterConfig(provider=IntentInterpreterProvider.OPENAI, model="gpt-5-nano")
    interpreter = create_intent_interpreter(config, api_key=_FAKE_API_KEY)
    assert isinstance(interpreter, OpenAIIntentInterpreter)


def test_create_intent_interpreter_openai_returns_something_satisfying_the_port():
    config = IntentInterpreterConfig(provider=IntentInterpreterProvider.OPENAI, model="gpt-5-nano")
    interpreter = create_intent_interpreter(config, api_key=_FAKE_API_KEY)

    assert callable(interpreter.interpret)
    params = inspect.signature(interpreter.interpret).parameters
    assert "natural_language_request" in params
    assert "request_id" in params
    assert params["natural_language_request"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["request_id"].kind == inspect.Parameter.KEYWORD_ONLY

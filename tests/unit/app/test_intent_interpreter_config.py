"""Unit tests for provider-neutral LLM interpreter configuration
(Batch 23, Task 1). No filesystem I/O, no real environment mutation —
every test injects a plain dict as `env`, mirroring `test_config.py`'s
own discipline exactly."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import SecretStr

from iac_agent.app.config import (
    IntentInterpreterProvider,
    MissingConfigurationError,
    load_intent_interpreter_config_from_env,
    load_openai_api_key_from_env,
)

_VALID_ENV = {
    "IAC_AGENT_LLM_PROVIDER": "openai",
    "IAC_AGENT_LLM_MODEL": "gpt-5-nano",
}


def test_load_config_with_valid_openai_provider_and_model():
    config = load_intent_interpreter_config_from_env(_VALID_ENV)

    assert config.provider == IntentInterpreterProvider.OPENAI
    assert config.model == "gpt-5-nano"


def test_load_config_missing_provider_raises_missing_configuration_error():
    env = dict(_VALID_ENV)
    del env["IAC_AGENT_LLM_PROVIDER"]
    with pytest.raises(MissingConfigurationError):
        load_intent_interpreter_config_from_env(env)


def test_load_config_missing_model_raises_missing_configuration_error():
    env = dict(_VALID_ENV)
    del env["IAC_AGENT_LLM_MODEL"]
    with pytest.raises(MissingConfigurationError):
        load_intent_interpreter_config_from_env(env)


def test_load_config_unknown_provider_string_raises_missing_configuration_error():
    env = {**_VALID_ENV, "IAC_AGENT_LLM_PROVIDER": "anthropic"}
    with pytest.raises(MissingConfigurationError):
        load_intent_interpreter_config_from_env(env)


def test_load_config_never_reads_openai_api_key():
    env = {"OPENAI_API_KEY": "sk-fake-not-real"}  # noqa: S105 - deliberately fake
    with pytest.raises(MissingConfigurationError):
        load_intent_interpreter_config_from_env(env)


def test_intent_interpreter_config_is_frozen():
    config = load_intent_interpreter_config_from_env(_VALID_ENV)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.model = "changed"


def test_load_openai_api_key_from_env_returns_secret_str():
    env = {"OPENAI_API_KEY": "sk-fake-not-real"}  # noqa: S105 - deliberately fake
    key = load_openai_api_key_from_env(env)

    assert isinstance(key, SecretStr)
    assert key.get_secret_value() == "sk-fake-not-real"


def test_load_openai_api_key_from_env_missing_raises_missing_configuration_error():
    with pytest.raises(MissingConfigurationError):
        load_openai_api_key_from_env({})


def test_load_openai_api_key_from_env_never_appears_in_repr():
    env = {"OPENAI_API_KEY": "sk-fake-not-real"}  # noqa: S105 - deliberately fake
    key = load_openai_api_key_from_env(env)

    assert "sk-fake-not-real" not in repr(key)
    assert "sk-fake-not-real" not in str(key)

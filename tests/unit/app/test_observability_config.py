"""Observability is off by default. An unavailable backend is a configuration error."""

from __future__ import annotations

import logging
from dataclasses import fields

import pytest

from iac_agent.app.composition import build_observability
from iac_agent.app.config import (
    ApplicationConfig,
    MissingConfigurationError,
    ObservabilityConfigurationError,
    ObservabilityMode,
    ObservabilitySettings,
    load_observability_settings_from_env,
)
from iac_agent.observability.models import GenerationTelemetry


def _generation() -> GenerationTelemetry:
    return GenerationTelemetry(
        request_id="req-001",
        provider="openai",
        model="gpt-test",
        prompt_version="4",
        latency_ms=1.0,
        attempt_count=1,
        outcome_category="ok",
    )


def test_default_env_is_off():
    assert load_observability_settings_from_env({}).mode is ObservabilityMode.OFF


@pytest.mark.parametrize("raw", ["", "off", "noop", "OFF"])
def test_disabled_settings_build_a_silent_port(raw, caplog):
    env = {} if raw == "" else {"IAC_AGENT_OBSERVABILITY": raw}
    settings = load_observability_settings_from_env(env)
    port = build_observability(settings)
    with caplog.at_level(logging.WARNING):
        port.record_generation(_generation())
        port.flush()
    assert caplog.records == []


def test_langfuse_is_recognized_and_rejected_until_the_adapter_exists():
    settings = load_observability_settings_from_env({"IAC_AGENT_OBSERVABILITY": "langfuse"})
    assert settings.mode is ObservabilityMode.LANGFUSE
    with pytest.raises(ObservabilityConfigurationError, match="langfuse"):
        build_observability(settings)


def test_unknown_backend_fails_at_load():
    with pytest.raises(MissingConfigurationError, match="datadog"):
        load_observability_settings_from_env({"IAC_AGENT_OBSERVABILITY": "datadog"})


def test_application_config_does_not_carry_observability_secrets():
    names = {item.name for item in fields(ApplicationConfig)}
    assert "langfuse" not in "".join(names)
    assert "api_key" not in names
    assert "token" not in names
    assert ObservabilitySettings(mode=ObservabilityMode.OFF).mode is ObservabilityMode.OFF
    assert issubclass(ObservabilityConfigurationError, MissingConfigurationError)

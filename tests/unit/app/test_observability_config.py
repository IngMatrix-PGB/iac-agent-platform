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


def test_langfuse_without_keys_fails_clearly_and_does_not_construct(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    def factory(env):
        raise AssertionError("factory must not run without both keys")

    settings = load_observability_settings_from_env({"IAC_AGENT_OBSERVABILITY": "langfuse"})
    assert settings.mode is ObservabilityMode.LANGFUSE
    with pytest.raises(ObservabilityConfigurationError, match="LANGFUSE_SECRET_KEY"):
        build_observability(
            settings,
            env={"LANGFUSE_PUBLIC_KEY": "pk-lf-not-a-real-key"},
            adapter_factory=factory,
        )


def test_langfuse_with_keys_uses_the_injected_factory_and_not_noop():
    sentinel_calls = []

    class _Sentinel:
        def record_generation(self, event) -> None:
            sentinel_calls.append(event.request_id)

        def record_resolution(self, event) -> None:
            return None

        def record_workflow(self, event) -> None:
            return None

        def flush(self) -> None:
            return None

    port = build_observability(
        ObservabilitySettings(mode=ObservabilityMode.LANGFUSE),
        env={"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"},
        adapter_factory=lambda env: _Sentinel(),
    )
    port.record_generation(_generation())
    assert sentinel_calls == ["req-001"]


def test_disabled_mode_does_not_call_the_langfuse_factory():
    def factory(env):
        raise AssertionError("NoOp must not construct Langfuse")

    port = build_observability(
        ObservabilitySettings(mode=ObservabilityMode.OFF),
        adapter_factory=factory,
    )
    port.flush()


def test_langfuse_construction_failure_hides_secret_text():
    def factory(env):
        raise RuntimeError(env["LANGFUSE_SECRET_KEY"])

    with pytest.raises(ObservabilityConfigurationError) as caught:
        build_observability(
            ObservabilitySettings(mode=ObservabilityMode.LANGFUSE),
            env={"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-do-not-log"},
            adapter_factory=factory,
        )
    assert "sk-lf-do-not-log" not in str(caught.value)
    assert "pk-lf-test" not in str(caught.value)


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

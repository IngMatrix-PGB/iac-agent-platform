"""Factory health checks. No cloud probes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import BIND_HOST, create_app
from iac_agent.app.capabilities import CapabilityPresence
from iac_agent.app.config import MissingConfigurationError

_CAPABILITY_NAMES = (
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_COMMIT_AUTHOR_NAME",
    "GITHUB_COMMIT_AUTHOR_EMAIL",
    "GITHUB_TOKEN",
    "GITHUB_BASE_BRANCH",
    "IAC_AGENT_LLM_PROVIDER",
    "IAC_AGENT_LLM_MODEL",
    "OPENAI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)
_GITHUB = {
    "GITHUB_OWNER": "example-user",
    "GITHUB_REPOSITORY": "iac-agent-platform",
    "GITHUB_COMMIT_AUTHOR_NAME": "Example Bot",
    "GITHUB_COMMIT_AUTHOR_EMAIL": "example-bot@example.invalid",
    "GITHUB_TOKEN": "test-github-token-not-used",
}
_INTENT = {
    "IAC_AGENT_LLM_PROVIDER": "openai",
    "IAC_AGENT_LLM_MODEL": "gpt-test",
    "OPENAI_API_KEY": "test-openai-key-not-used",
}


def _isolated_env(monkeypatch, tmp_path: Path, **extra: str) -> None:
    for name in _CAPABILITY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "probe-secret-must-not-leak")
    monkeypatch.setenv("IAC_AGENT_OBSERVABILITY", "off")
    monkeypatch.setenv("IAC_AGENT_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("IAC_AGENT_STATE_DB", str(tmp_path / "state.db"))
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def _forbid_network(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    import httpx

    monkeypatch.setattr(httpx.Client, "send", boom)


def test_health_and_ready_with_holder():
    app = create_app(holder=object())
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    rendered = health.text + ready.text
    assert "state.db" not in rendered
    assert "artifacts" not in rendered
    assert "GITHUB" not in rendered


def test_health_and_ready_stay_anonymous_when_a_secret_is_configured():
    app = create_app(holder=object(), operator_secret=SecretStr("probe-secret-must-not-leak"))
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert ready.status_code == 200
    assert "probe-secret-must-not-leak" not in health.text
    assert "probe-secret-must-not-leak" not in ready.text


def test_lifespan_rejects_a_missing_operator_secret(monkeypatch):
    monkeypatch.delenv("IAC_AGENT_OPERATOR_SECRET", raising=False)
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    message = str(exc.value)
    assert "IAC_AGENT_OPERATOR_SECRET" in message
    assert "probe-secret-must-not-leak" not in message


def test_lifespan_rejects_an_empty_operator_secret(monkeypatch):
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    assert str(exc.value) == (
        "IAC_AGENT_OPERATOR_SECRET must be set explicitly — there is no default operator secret"
    )


def test_lifespan_rejects_a_blank_operator_secret_without_echoing_it(monkeypatch):
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "   ")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    assert str(exc.value) == (
        "IAC_AGENT_OPERATOR_SECRET must be set explicitly — there is no default operator secret"
    )


def test_lifespan_starts_when_optional_capabilities_are_absent(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, GITHUB_BASE_BRANCH="main")
    monkeypatch.setattr(
        "iac_agent.app.composition.GitHubSourceControl",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GitHubSourceControl")),
    )
    monkeypatch.setattr(
        "iac_agent.intent.adapters.openai.OpenAIIntentInterpreter",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OpenAIIntentInterpreter")),
    )
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        listed = client.get(
            "/api/v1/requests",
            headers={"Authorization": "Bearer probe-secret-must-not-leak"},
        )
        missing = client.get(
            "/api/v1/requests/req-missing",
            headers={"Authorization": "Bearer probe-secret-must-not-leak"},
        )
        holder = app.state.holder
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    rendered = health.text + ready.text
    assert "probe-secret-must-not-leak" not in rendered
    assert "GITHUB_TOKEN" not in rendered
    assert "OPENAI_API_KEY" not in rendered
    assert holder.capabilities.source_control_publishing is CapabilityPresence.ABSENT
    assert holder.capabilities.intent_interpretation is CapabilityPresence.ABSENT
    assert holder.intent_service is None
    assert listed.status_code == 200
    assert listed.json() == {"requests": []}
    assert missing.status_code == 404
    assert missing.json() == {"error": "request_not_found", "message": "Request not found."}


def test_lifespan_configures_only_the_interpreter(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, **_INTENT)
    _forbid_network(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        holder = app.state.holder
    assert holder.capabilities.intent_interpretation is CapabilityPresence.CONFIGURED
    assert holder.capabilities.source_control_publishing is CapabilityPresence.ABSENT
    assert holder.intent_service is not None


def test_lifespan_configures_only_source_control(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, **_GITHUB)
    _forbid_network(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        holder = app.state.holder
    assert holder.capabilities.source_control_publishing is CapabilityPresence.CONFIGURED
    assert holder.capabilities.intent_interpretation is CapabilityPresence.ABSENT
    assert holder.intent_service is None


def test_lifespan_configures_both_optional_capabilities_without_network(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, **_GITHUB, **_INTENT)
    _forbid_network(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        holder = app.state.holder
    assert holder.capabilities.intent_interpretation is CapabilityPresence.CONFIGURED
    assert holder.capabilities.source_control_publishing is CapabilityPresence.CONFIGURED
    assert holder.intent_service is not None


def test_lifespan_rejects_partial_github_configuration(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, GITHUB_OWNER="example-user")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    text = str(exc.value)
    assert "GITHUB_TOKEN" in text
    assert "probe-secret-must-not-leak" not in text
    assert "example-user" not in text


def test_lifespan_rejects_partial_interpreter_configuration(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, IAC_AGENT_LLM_PROVIDER="openai")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    text = str(exc.value)
    assert "IAC_AGENT_LLM_MODEL" in text
    assert "probe-secret-must-not-leak" not in text


def test_lifespan_still_rejects_langfuse_without_keys(monkeypatch, tmp_path):
    _isolated_env(monkeypatch, tmp_path, IAC_AGENT_OBSERVABILITY="langfuse")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    assert "LANGFUSE_PUBLIC_KEY" in str(exc.value)


def test_state_plane_failure_prevents_startup(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    _isolated_env(monkeypatch, tmp_path, GITHUB_BASE_BRANCH="main")
    monkeypatch.setenv("IAC_AGENT_STATE_DB", str(blocker / "state.db"))
    app = create_app()
    with pytest.raises(OSError):
        with TestClient(app):
            pass


def test_checkpointer_closes_when_startup_fails_after_open(monkeypatch, tmp_path):
    import sqlite3

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr("iac_agent.persistence.checkpoints.sqlite3.connect", tracking_connect)
    _isolated_env(monkeypatch, tmp_path, IAC_AGENT_OBSERVABILITY="langfuse")
    app = create_app()
    with pytest.raises(MissingConfigurationError):
        with TestClient(app):
            pass
    assert opened
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("select 1")


def test_ready_without_holder_is_503():
    app = create_app(holder=object())
    with TestClient(app) as client:
        app.state.holder = None
        ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}


def test_bind_host_is_loopback():
    assert BIND_HOST == "127.0.0.1"

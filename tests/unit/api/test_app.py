"""Factory health checks. No cloud probes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import BIND_HOST, create_app
from iac_agent.app.config import MissingConfigurationError


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


def test_lifespan_rejects_a_blank_operator_secret_without_echoing_it(monkeypatch):
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "   ")
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    assert str(exc.value) == (
        "IAC_AGENT_OPERATOR_SECRET must be set explicitly — there is no default operator secret"
    )


def test_lifespan_still_requires_github_after_the_operator_secret(monkeypatch):
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "probe-secret-must-not-leak")
    monkeypatch.delenv("GITHUB_OWNER", raising=False)
    app = create_app()
    with pytest.raises(MissingConfigurationError) as exc:
        with TestClient(app):
            pass
    message = str(exc.value)
    assert "GITHUB_OWNER" in message
    assert "probe-secret-must-not-leak" not in message


def test_ready_without_holder_is_503():
    app = create_app(holder=object())
    with TestClient(app) as client:
        app.state.holder = None
        ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}


def test_bind_host_is_loopback():
    assert BIND_HOST == "127.0.0.1"

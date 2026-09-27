"""Factory health checks. No cloud probes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from iac_agent.api.app import BIND_HOST, create_app


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


def test_ready_without_holder_is_503():
    app = create_app(holder=object())
    with TestClient(app) as client:
        app.state.holder = None
        ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready"}


def test_bind_host_is_loopback():
    assert BIND_HOST == "127.0.0.1"

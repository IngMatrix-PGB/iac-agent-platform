"""The browser fake enforces the same 401 contract as the operator API."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from iac_agent.api import routes

_UNAUTHORIZED = {"error": "unauthenticated", "message": "Authentication is required."}


def _fake():
    path = Path(__file__).resolve().parents[2] / "browser" / "serve_fake_ui.py"
    spec = importlib.util.spec_from_file_location("serve_fake_ui_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fake_operator_routes_require_the_bearer():
    module = _fake()
    original = routes.generate_request_id
    try:
        app = module.build_app()
        with TestClient(app) as client:
            missing = client.get("/api/v1/requests")
            wrong = client.get(
                "/api/v1/requests/req-indexed",
                headers={"Authorization": "Bearer wrong-operator-secret"},
            )
            health = client.get("/health")
            listed = client.get(
                "/api/v1/requests",
                headers={"Authorization": f"Bearer {module.OPERATOR_SECRET}"},
            )
    finally:
        routes.generate_request_id = original

    assert missing.status_code == 401
    assert missing.json() == _UNAUTHORIZED
    assert module.OPERATOR_SECRET not in missing.text
    assert wrong.status_code == 401
    assert wrong.json() == _UNAUTHORIZED
    assert "wrong-operator-secret" not in wrong.text
    assert health.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["requests"][0]["request_id"] == "req-indexed"
    assert "aws_sqs_queue.hidden_address" not in listed.text
    assert "HIDDEN_FINDING_MESSAGE" not in listed.text

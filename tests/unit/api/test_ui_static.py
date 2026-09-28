"""Static operator UI hosting. The SPA fallback must not shadow the API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from iac_agent.api.app import create_app
from iac_agent.api.ui_static import load_ui_dist


class _Application:
    def read(self, request_id: str):
        del request_id
        return None

    def resume(self, request_id: str, decision: object):
        raise AssertionError(f"unused resume {request_id} {decision}")


class _Intent:
    def submit(self, *, request_id: str, natural_language_request: str):
        raise AssertionError(f"unused submit {request_id} {natural_language_request}")


class _Holder:
    def __init__(self) -> None:
        self.application = _Application()
        self.intent_service = _Intent()


def _dist(tmp_path):
    dist = tmp_path / "ui"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><title>IaC Agent Platform</title>", encoding="utf-8"
    )
    (dist / "assets").mkdir()
    (dist / "assets" / "app.css").write_text("body{margin:0}", encoding="utf-8")
    return dist


def test_packaged_ui_serves_html_and_leaves_api_routes_json(tmp_path):
    dist = _dist(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("OUTSIDE_DIST", encoding="utf-8")
    app = create_app(_Holder(), ui_dist=dist)
    with TestClient(app) as client:
        root = client.get("/")
        deep = client.get("/requests/req-example")
        missing = client.get("/api/v1/requests/req-missing")
        unknown = client.get("/api/v1/nonexistent")
        health = client.get("/health")
        ready = client.get("/ready")
        asset = client.get("/assets/app.css")
        escaped = client.get("/assets/../index.html")
        escaped_secret = client.get("/assets/../../secret.txt")

    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert "IaC Agent Platform" in root.text
    assert deep.status_code == 200
    assert "text/html" in deep.headers["content-type"]
    assert "IaC Agent Platform" in deep.text
    assert missing.status_code == 404
    assert missing.json()["error"] == "request_not_found"
    assert "text/html" not in missing.headers["content-type"]
    assert unknown.status_code == 404
    assert "application/json" in unknown.headers["content-type"]
    assert unknown.json() == {"detail": "Not Found"}
    assert "<title>" not in unknown.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert asset.status_code == 200
    assert asset.text == "body{margin:0}"
    assert "OUTSIDE_DIST" not in escaped.text
    assert "OUTSIDE_DIST" not in escaped_secret.text
    content_type = escaped.headers["content-type"]
    assert "<title>" in escaped.text or content_type.startswith("application/json")


def test_create_app_without_ui_dist_does_not_serve_html():
    app = create_app(_Holder())
    with TestClient(app) as client:
        root = client.get("/")
    assert "<title>" not in root.text


def test_load_ui_dist_requires_an_index(tmp_path):
    dist = _dist(tmp_path)
    assert load_ui_dist({}) is None
    assert load_ui_dist({"IAC_AGENT_UI_DIST": "  "}) is None
    assert load_ui_dist({"IAC_AGENT_UI_DIST": str(dist)}) == dist
    try:
        load_ui_dist({"IAC_AGENT_UI_DIST": str(tmp_path / "missing")})
    except FileNotFoundError:
        return
    raise AssertionError("missing index.html must raise FileNotFoundError")

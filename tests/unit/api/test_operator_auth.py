"""Operator routes reject anonymous callers before application behavior."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import create_app

_SECRET = "test-operator-secret"
_UNAUTHORIZED = {"error": "unauthenticated", "message": "Authentication is required."}


class _Application:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.lists: list[int] = []
        self.resumes: list[tuple[str, object]] = []

    def read(self, request_id: str):
        self.reads.append(request_id)
        return None

    def list_requests(self, limit: int):
        self.lists.append(limit)
        return ()

    def resume(self, request_id: str, decision: object):
        self.resumes.append((request_id, decision))
        raise AssertionError("resume must not run")


class _Intent:
    def __init__(self) -> None:
        self.submits: list[tuple[str, str]] = []

    def submit(self, *, request_id: str, natural_language_request: str):
        self.submits.append((request_id, natural_language_request))
        raise AssertionError("submit must not run")


class _Holder:
    def __init__(self) -> None:
        self.application = _Application()
        self.intent_service = _Intent()


def _client(holder: _Holder) -> TestClient:
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    return TestClient(app)


def _assert_unauthorized(response, holder: _Holder) -> None:
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED
    assert "request_id" not in response.json()
    assert _SECRET not in response.text
    assert "wrong-secret" not in response.text
    assert holder.application.reads == []
    assert holder.application.lists == []
    assert holder.application.resumes == []
    assert holder.intent_service.submits == []


def test_anonymous_operator_routes_are_401(caplog):
    holder = _Holder()
    client = _client(holder)
    caplog.set_level(logging.DEBUG)
    calls = [
        client.post("/api/v1/requests", json={"natural_language_request": "queue"}),
        client.get("/api/v1/requests"),
        client.get("/api/v1/requests/req-missing"),
        client.post("/api/v1/requests/req-missing/approval", json={"decision": "approve"}),
    ]
    for response in calls:
        _assert_unauthorized(response, holder)
    assert _SECRET not in caplog.text


def test_wrong_bearer_and_wrong_scheme_match_anonymous_401(caplog):
    holder = _Holder()
    client = _client(holder)
    caplog.set_level(logging.DEBUG)
    wrong = {"Authorization": "Bearer wrong-secret"}
    basic = {"Authorization": f"Basic {_SECRET}"}
    empty = {"Authorization": "Bearer "}
    malformed = {"Authorization": f"Bearer {_SECRET} extra"}
    for headers in (wrong, basic, empty, malformed):
        detail = client.get("/api/v1/requests/req-missing", headers=headers)
        approval = client.post(
            "/api/v1/requests/req-missing/approval",
            json={"decision": "approve"},
            headers=headers,
        )
        _assert_unauthorized(detail, holder)
        _assert_unauthorized(approval, holder)
        assert detail.json() == approval.json() == _UNAUTHORIZED
    assert _SECRET not in caplog.text
    assert "wrong-secret" not in caplog.text

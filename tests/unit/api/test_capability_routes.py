"""Operation-boundary capability gates. No provider calls."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from iac_agent.api.app import create_app
from iac_agent.app.capabilities import (
    INTENT_ABSENT_MESSAGE,
    CapabilityPresence,
    RuntimeCapabilities,
)

_SECRET = "test-operator-secret"
_OPENAI_VALUE = "test-openai-key-not-used"


class _Application:
    def __init__(self) -> None:
        self.stored: dict[str, object] = {}
        self.checkpoints: dict[str, object] = {}
        self.index: dict[str, object] = {}
        self.reads: list[str] = []
        self.submits: list[str] = []
        self.invokes: list[str] = []

    def read(self, request_id: str):
        self.reads.append(request_id)
        return self.stored.get(request_id)

    def submit(self, request_id: str):
        self.submits.append(request_id)
        raise AssertionError("application.submit must not run")

    def invoke(self, request_id: str):
        self.invokes.append(request_id)
        raise AssertionError("graph.invoke must not run")


class _Intent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.interprets: list[str] = []

    def interpret(self, text: str):
        self.interprets.append(text)
        raise AssertionError("interpret must not run")

    def submit(self, *, request_id: str, natural_language_request: str):
        self.calls.append((request_id, natural_language_request))
        raise AssertionError("submit must not run")


class _Holder:
    def __init__(self) -> None:
        self.application = _Application()
        self.intent_service = _Intent()
        self.capabilities = RuntimeCapabilities(
            intent_interpretation=CapabilityPresence.ABSENT,
            source_control_publishing=CapabilityPresence.ABSENT,
        )


def _client(holder: _Holder) -> TestClient:
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {_SECRET}"
    return client


def _post(client: TestClient, request_id: str):
    return client.post(
        "/api/v1/requests",
        json={"natural_language_request": "build a queue", "request_id": request_id},
    )


def test_new_request_without_an_interpreter_does_not_submit():
    holder = _Holder()
    response = _post(_client(holder), "req-new")
    assert response.status_code == 503
    assert response.json() == {
        "error": "capability_unavailable",
        "message": INTENT_ABSENT_MESSAGE,
    }
    assert "request_id" not in response.json()
    assert _SECRET not in response.text
    assert _OPENAI_VALUE not in response.text
    assert holder.intent_service.calls == []
    assert holder.intent_service.interprets == []
    assert holder.application.submits == []
    assert holder.application.invokes == []
    assert "req-new" not in holder.application.checkpoints
    assert "req-new" not in holder.application.index
    assert "req-new" not in holder.application.stored


def test_existing_request_still_conflicts_without_an_interpreter():
    holder = _Holder()
    holder.application.stored["req-old"] = object()
    response = _post(_client(holder), "req-old")
    assert response.status_code == 409
    assert response.json()["error"] == "request_exists"
    assert holder.intent_service.calls == []
    assert holder.intent_service.interprets == []


def test_unauthenticated_submit_is_401_before_the_capability_check():
    holder = _Holder()
    app = create_app(holder=holder, operator_secret=SecretStr(_SECRET))
    response = TestClient(app).post(
        "/api/v1/requests",
        json={"natural_language_request": "build a queue", "request_id": "req-new"},
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthenticated",
        "message": "Authentication is required.",
    }
    assert holder.application.reads == []
    assert holder.intent_service.calls == []

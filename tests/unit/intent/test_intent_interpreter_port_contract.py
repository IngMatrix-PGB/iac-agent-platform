"""Tests for `IntentInterpreterPort`, its typed failure hierarchy, and
`parse_intent_payload` (Batch 21, Task 5, spec §6, §10, §11).

`FakeIntentInterpreter` is defined here, in the test file that uses it
— never importable from `src/` (spec §1.3).
"""

from __future__ import annotations

import pytest

from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentSchemaVersionUnsupportedError,
    IntentValidationError,
    parse_intent_payload,
)

_VALID_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "api",
    "interaction_pattern": "synchronous",
    "capabilities": ["http_endpoint"],
}


class FakeIntentInterpreter:
    """Configurable with either a canned raw payload (fed through
    `parse_intent_payload`) or a pre-selected exception to raise —
    mirrors what a real adapter would eventually do, without any
    network call or provider dependency."""

    def __init__(self, *, payload: dict | None = None, raises: Exception | None = None):
        self._payload = payload
        self._raises = raises

    def interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent:
        if self._raises is not None:
            raise self._raises
        assert self._payload is not None
        return parse_intent_payload(self._payload)


@pytest.mark.parametrize(
    "subtype",
    [
        IntentSchemaVersionUnsupportedError,
        IntentValidationError,
        IntentProviderUnavailableError,
        IntentProviderTimeoutError,
        IntentProviderRefusalError,
    ],
)
def test_intent_interpreter_error_hierarchy_bases(subtype):
    assert issubclass(subtype, IntentInterpreterError)
    assert issubclass(IntentInterpreterError, Exception)


def test_parse_intent_payload_valid_payload_returns_architecture_intent():
    intent = parse_intent_payload(_VALID_PAYLOAD)
    assert isinstance(intent, ArchitectureIntent)
    assert intent.workload_type.value == "api"


def test_parse_intent_payload_wrong_schema_version_raises_before_field_validation():
    payload = {**_VALID_PAYLOAD, "schema_version": "2", "workload_type": "not-a-real-workload"}
    with pytest.raises(IntentSchemaVersionUnsupportedError):
        parse_intent_payload(payload)


def test_parse_intent_payload_unknown_capability_raises_intent_validation_error():
    payload = {**_VALID_PAYLOAD, "capabilities": ["background_processing"]}
    with pytest.raises(IntentValidationError):
        parse_intent_payload(payload)


def test_parse_intent_payload_missing_required_field_raises_intent_validation_error():
    payload = {"schema_version": "1", "capabilities": ["http_endpoint"]}
    with pytest.raises(IntentValidationError):
        parse_intent_payload(payload)


def test_parse_intent_payload_wrong_type_raises_intent_validation_error():
    payload = {**_VALID_PAYLOAD, "capabilities": "http_endpoint"}
    with pytest.raises(IntentValidationError):
        parse_intent_payload(payload)


def test_fake_interpreter_returns_valid_architecture_intent_for_canned_payload():
    fake = FakeIntentInterpreter(payload=_VALID_PAYLOAD)
    intent = fake.interpret(natural_language_request="build me an api", request_id="req-001")
    assert isinstance(intent, ArchitectureIntent)


def test_fake_interpreter_raises_intent_schema_version_unsupported_error_for_configured_payload():
    fake = FakeIntentInterpreter(payload={**_VALID_PAYLOAD, "schema_version": "9"})
    with pytest.raises(IntentSchemaVersionUnsupportedError):
        fake.interpret(natural_language_request="x", request_id="req-001")


def test_fake_interpreter_raises_intent_validation_error_for_configured_payload():
    fake = FakeIntentInterpreter(payload={**_VALID_PAYLOAD, "capabilities": ["not_real"]})
    with pytest.raises(IntentValidationError):
        fake.interpret(natural_language_request="x", request_id="req-001")


def test_fake_interpreter_raises_intent_provider_unavailable_error_when_configured():
    fake = FakeIntentInterpreter(raises=IntentProviderUnavailableError("provider unreachable"))
    with pytest.raises(IntentProviderUnavailableError):
        fake.interpret(natural_language_request="x", request_id="req-001")


def test_fake_interpreter_raises_intent_provider_timeout_error_when_configured():
    fake = FakeIntentInterpreter(raises=IntentProviderTimeoutError("provider timed out"))
    with pytest.raises(IntentProviderTimeoutError):
        fake.interpret(natural_language_request="x", request_id="req-001")


def test_fake_interpreter_raises_intent_provider_refusal_error_when_configured():
    fake = FakeIntentInterpreter(raises=IntentProviderRefusalError("provider refused"))
    with pytest.raises(IntentProviderRefusalError):
        fake.interpret(natural_language_request="x", request_id="req-001")

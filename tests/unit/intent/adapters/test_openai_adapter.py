"""Unit tests for `OpenAIIntentInterpreter` (Batch 23, Tasks 3-5).

Every test injects a `FakeOpenAIClient` (defined here, never importable
from `src/`, per the existing fakes-in-tests convention) — zero real
network calls, zero real API key required anywhere in this file.
"""

from __future__ import annotations

import logging

import httpx
import openai
import pytest
from pydantic import SecretStr

from iac_agent.intent.adapters.openai import OpenAIIntentInterpreter
from iac_agent.intent.models import Capability, InteractionPattern, WorkloadType
from iac_agent.intent.port import (
    IntentInterpreterError,
    IntentProviderRefusalError,
    IntentProviderTimeoutError,
    IntentProviderUnavailableError,
    IntentValidationError,
)

_FAKE_API_KEY = SecretStr("sk-fake-not-real")
_REQUEST_ID = "req-001"


def _fake_http_request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid")


def _fake_http_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_fake_http_request())


def _rate_limit_error() -> openai.RateLimitError:
    return openai.RateLimitError(
        message="rate limited", response=_fake_http_response(429), body=None
    )


def _auth_error() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        message="invalid api key", response=_fake_http_response(401), body=None
    )


class _FakeParsedPayload:
    """Stands in for the Pydantic instance `response.output_parsed`
    would hold on a real SDK response — only needs `.model_dump()`."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self, *, mode: str = "python"):
        return dict(self._data)


class _FakeResponse:
    def __init__(self, *, output_parsed=None):
        self.output_parsed = output_parsed


def _valid_payload() -> dict:
    return {
        "workload_type": WorkloadType.API.value,
        "interaction_pattern": InteractionPattern.SYNCHRONOUS.value,
        "capabilities": [Capability.HTTP_ENDPOINT.value],
        "logical_name_hint": None,
        "user_provided_hints": [],
        "assumptions": [],
        "unresolved_questions": [],
        "confidence": None,
    }


class _FakeResponsesNamespace:
    def __init__(self, results):
        # results: list of Exception instances (raised) or _FakeResponse
        # instances (returned), consumed in order, one per call.
        self._results = list(results)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeOpenAIClient:
    def __init__(self, results):
        self.responses = _FakeResponsesNamespace(results)


def _adapter(results) -> tuple[OpenAIIntentInterpreter, FakeOpenAIClient]:
    client = FakeOpenAIClient(results)
    adapter = OpenAIIntentInterpreter(model="gpt-5-nano", api_key=_FAKE_API_KEY, client=client)
    return adapter, client


# ---------------------------------------------------------------------------
# Task 3: structured-output request/response boundary
# ---------------------------------------------------------------------------


def test_successful_response_produces_valid_architecture_intent():
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    intent = adapter.interpret(natural_language_request="build me an api", request_id=_REQUEST_ID)
    assert intent.workload_type == WorkloadType.API
    assert intent.schema_version == "1"


def test_adapter_injects_schema_version_not_the_model():
    payload = _valid_payload()
    adapter, client = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    adapter.interpret(natural_language_request="build me an api", request_id=_REQUEST_ID)
    # The model's own schema (text_format) never includes schema_version.
    call_kwargs = client.responses.calls[0]
    text_format = call_kwargs["text_format"]
    assert "schema_version" not in getattr(text_format, "model_fields", {})


def test_null_logical_name_hint_passes_through_as_none():
    payload = _valid_payload()
    payload["logical_name_hint"] = None
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    intent = adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert intent.logical_name_hint is None


def test_null_confidence_passes_through_as_none():
    payload = _valid_payload()
    payload["confidence"] = None
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    intent = adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert intent.confidence is None


def test_empty_arrays_for_hints_assumptions_unresolved_questions_are_valid():
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    intent = adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert intent.user_provided_hints == ()
    assert intent.assumptions == ()
    assert intent.unresolved_questions == ()


def test_malformed_response_raises_intent_validation_error():
    payload = _valid_payload()
    del payload["workload_type"]
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    with pytest.raises(IntentValidationError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_unknown_capability_in_response_raises_intent_validation_error():
    payload = _valid_payload()
    payload["capabilities"] = ["not_a_real_capability"]
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    with pytest.raises(IntentValidationError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_provider_specific_response_object_never_returned_or_leaked():
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    result = adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    from iac_agent.intent.models import ArchitectureIntent

    assert type(result) is ArchitectureIntent


# ---------------------------------------------------------------------------
# Task 4: error normalization + bounded retry
# ---------------------------------------------------------------------------


def test_connection_failure_raises_intent_provider_unavailable_error():
    adapter, _ = _adapter(
        [
            openai.APIConnectionError(request=_fake_http_request()),
            openai.APIConnectionError(request=_fake_http_request()),
        ]
    )
    with pytest.raises(IntentProviderUnavailableError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_rate_limit_raises_intent_provider_unavailable_error():
    adapter, _ = _adapter(
        [
            _rate_limit_error(),
            _rate_limit_error(),
        ]
    )
    with pytest.raises(IntentProviderUnavailableError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_timeout_raises_intent_provider_timeout_error():
    adapter, _ = _adapter(
        [
            openai.APITimeoutError(request=_fake_http_request()),
            openai.APITimeoutError(request=_fake_http_request()),
        ]
    )
    with pytest.raises(IntentProviderTimeoutError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_refusal_field_raises_intent_provider_refusal_error():
    adapter, _ = _adapter([_FakeResponse(output_parsed=None)])
    with pytest.raises(IntentProviderRefusalError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_authentication_error_at_request_time_raises_intent_provider_unavailable_error():
    adapter, _ = _adapter([_auth_error()])
    with pytest.raises(IntentProviderUnavailableError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


@pytest.mark.parametrize(
    "raw_exc",
    [
        openai.APIConnectionError(request=_fake_http_request()),
        openai.APITimeoutError(request=_fake_http_request()),
    ],
)
def test_no_provider_sdk_exception_escapes_interpret(raw_exc):
    adapter, _ = _adapter([raw_exc, raw_exc])
    with pytest.raises(IntentInterpreterError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)


def test_connection_failure_retries_exactly_once_then_succeeds():
    adapter, client = _adapter(
        [
            openai.APIConnectionError(request=_fake_http_request()),
            _FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload())),
        ]
    )
    intent = adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert intent.workload_type == WorkloadType.API
    assert len(client.responses.calls) == 2


def test_connection_failure_retries_exactly_once_then_still_fails():
    adapter, client = _adapter(
        [
            openai.APIConnectionError(request=_fake_http_request()),
            openai.APIConnectionError(request=_fake_http_request()),
        ]
    )
    with pytest.raises(IntentProviderUnavailableError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert len(client.responses.calls) == 2


def test_refusal_is_never_retried():
    adapter, client = _adapter(
        [
            _FakeResponse(output_parsed=None),
            _FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload())),
        ]
    )
    with pytest.raises(IntentProviderRefusalError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert len(client.responses.calls) == 1


def test_malformed_payload_is_never_retried():
    bad_payload = _valid_payload()
    del bad_payload["workload_type"]
    adapter, client = _adapter(
        [
            _FakeResponse(output_parsed=_FakeParsedPayload(bad_payload)),
            _FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload())),
        ]
    )
    with pytest.raises(IntentValidationError):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    assert len(client.responses.calls) == 1


def test_no_automatic_fallback_to_another_provider():
    import inspect

    source = inspect.getsource(OpenAIIntentInterpreter)
    for forbidden in ("anthropic", "bedrock", "Anthropic", "Bedrock"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Task 5: privacy-safe telemetry
# ---------------------------------------------------------------------------


def test_successful_call_logs_only_safe_metadata_fields(caplog):
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    with caplog.at_level(logging.INFO, logger="iac_agent.intent.adapters.openai"):
        adapter.interpret(natural_language_request="secret request text", request_id=_REQUEST_ID)
    record = caplog.records[-1]
    assert record.request_id == _REQUEST_ID
    assert record.provider == "openai"
    assert record.model == "gpt-5-nano"
    assert record.outcome_category == "schema_valid"
    assert hasattr(record, "attempt_count")
    assert hasattr(record, "latency_ms")


def test_log_record_never_contains_raw_natural_language_request(caplog):
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    with caplog.at_level(logging.INFO, logger="iac_agent.intent.adapters.openai"):
        adapter.interpret(
            natural_language_request="this exact secret sentence must never be logged",
            request_id=_REQUEST_ID,
        )
    for record in caplog.records:
        assert "this exact secret sentence must never be logged" not in record.getMessage()
        assert "this exact secret sentence must never be logged" not in str(record.__dict__)


def test_log_record_never_contains_raw_response_body(caplog):
    payload = _valid_payload()
    payload["assumptions"] = ["a very specific raw assumption string"]
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(payload))])
    with caplog.at_level(logging.INFO, logger="iac_agent.intent.adapters.openai"):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    for record in caplog.records:
        assert "a very specific raw assumption string" not in str(record.__dict__)


def test_log_record_never_contains_api_key_value(caplog):
    adapter, _ = _adapter([_FakeResponse(output_parsed=_FakeParsedPayload(_valid_payload()))])
    with caplog.at_level(logging.INFO, logger="iac_agent.intent.adapters.openai"):
        adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    for record in caplog.records:
        assert "sk-fake-not-real" not in str(record.__dict__)


def test_failure_call_logs_outcome_category_matching_the_raised_error(caplog):
    adapter, _ = _adapter([_FakeResponse(output_parsed=None)])
    with caplog.at_level(logging.INFO, logger="iac_agent.intent.adapters.openai"):
        with pytest.raises(IntentProviderRefusalError):
            adapter.interpret(natural_language_request="x", request_id=_REQUEST_ID)
    record = caplog.records[-1]
    assert record.outcome_category == "refusal"



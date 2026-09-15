"""The interpreter port and its typed failure hierarchy (Batch 21).

Mirrors `iac_agent.git.port.SourceControlPort`'s exact shape: a narrow,
call-shaped `Protocol` with one method; success returns the value type
directly; failure raises a typed exception — never a result union for
the failure path (that would blur the system-failure/business-outcome
distinction this exception hierarchy exists to preserve).

No adapter is implemented this batch. `parse_intent_payload` is the
§6 parsing/validation boundary every future concrete adapter (e.g. a
`structured_llm.py`, co-located here like `iac_agent.git.github` sits
next to `iac_agent.git.port`) will call after obtaining a raw payload
from its provider — it is placed here, next to the exceptions it
raises, rather than duplicated per adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import ValidationError

from iac_agent.intent.models import ArchitectureIntent

_SUPPORTED_SCHEMA_VERSION = "1"


class IntentInterpreterError(Exception):
    """Base for every interpreter/system failure — mirrors
    `SourceControlError`/`CheckovError`'s own base-exception convention.
    Raised *before* an `ArchitectureIntent` exists at all;
    `ArchitectureResolver.resolve()` is never invoked for any of these.
    """


class IntentSchemaVersionUnsupportedError(IntentInterpreterError):
    """The raw payload's `schema_version` does not match the one
    currently-supported literal. Raised before full model validation is
    attempted, so a version bump always fails with a specific,
    unambiguous error rather than a wall of unrelated per-field
    validation errors."""


class IntentValidationError(IntentInterpreterError):
    """The raw payload failed `ArchitectureIntent.model_validate` for
    any other reason (unknown capability string, wrong type, missing
    required field, value outside a bound)."""


class IntentProviderUnavailableError(IntentInterpreterError):
    """The interpreter's provider could not be reached at all."""


class IntentProviderTimeoutError(IntentInterpreterError):
    """The interpreter's provider did not respond in time."""


class IntentProviderRefusalError(IntentInterpreterError):
    """The interpreter's provider declined to produce a structured
    response."""


class IntentInterpreterPort(Protocol):
    """One high-level operation: turn natural language into a validated
    `ArchitectureIntent`. Success returns the value type directly;
    failure raises an `IntentInterpreterError` subtype."""

    def interpret(
        self, *, natural_language_request: str, request_id: str
    ) -> ArchitectureIntent: ...


def parse_intent_payload(raw_payload: Mapping[str, Any]) -> ArchitectureIntent:
    """The exact three-step parsing/validation boundary (spec §6):

    1. Check `schema_version` against the one supported literal first —
       mismatch raises `IntentSchemaVersionUnsupportedError` immediately,
       before any field-level validation is attempted.
    2. `ArchitectureIntent.model_validate(raw_payload)` — any Pydantic
       `ValidationError` (unknown capability, wrong type, missing
       field, out-of-bounds value) is wrapped into `IntentValidationError`.
    3. Only a value that survives both checks is ever a real
       `ArchitectureIntent` instance.
    """
    schema_version = raw_payload.get("schema_version")
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise IntentSchemaVersionUnsupportedError(
            f"unsupported schema_version: {schema_version!r} "
            f"(expected {_SUPPORTED_SCHEMA_VERSION!r})"
        )

    try:
        return ArchitectureIntent.model_validate(raw_payload)
    except ValidationError as exc:
        raise IntentValidationError(f"invalid architecture intent payload: {exc.error_count()} "
                                     "error(s)") from exc

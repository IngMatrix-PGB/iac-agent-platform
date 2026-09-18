"""Sanitized Layer 2 eval diagnostics (Batch 23, Task 11).

Eval-layer only: never imported by `iac_agent.intent` domain code.
Persists a closed allowlist of normalized fields so a real-model run
can be diagnosed without a second provider call and without retaining
raw prompts, raw provider bodies, advisory free text, or secrets.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evals.scenarios.architecture_intent_nl_loader import ExpectedOutcome, Scenario
from iac_agent.domain.evals import EvalResult
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import ArchitectureResolver

DEFAULT_LAYER2_DIAGNOSTIC_DIR = Path("artifacts") / "evals" / "layer2"
DEFAULT_LAYER2_DIAGNOSTIC_PATH = DEFAULT_LAYER2_DIAGNOSTIC_DIR / "layer2-diagnostic.json"

_EVAL_REQUEST_ID = "layer2-eval-fixture-request"

_ALLOWED_DOCUMENT_KEYS = frozenset({"run", "results"})
_ALLOWED_RUN_KEYS = frozenset(
    {
        "provider",
        "model",
        "prompt_version",
        "dataset_path",
        "scenario_count",
        "evaluation_count",
    }
)
_ALLOWED_RESULT_KEYS = frozenset(
    {
        "scenario_id",
        "evaluator",
        "status",
        "expected_normalized",
        "actual_normalized",
        "failure_message_sanitized",
        "attempt_count",
        "token_metadata",
        "outcome_category",
        "resolver_outcome_expected",
        "resolver_outcome_actual",
        "provider",
        "model",
        "prompt_version",
    }
)
_ALLOWED_NORMALIZED_KEYS = frozenset(
    {
        "workload_type",
        "interaction_pattern",
        "capabilities",
        "user_provided_hints",
        "unresolved_questions_present",
        "unresolved_questions_count",
        "unresolved_questions_expected",
    }
)
_ALLOWED_TOKEN_KEYS = frozenset({"input_tokens", "output_tokens"})
_FORBIDDEN_KEYS = frozenset(
    {
        "natural_language_request",
        "assumptions",
        "unresolved_questions",
        "logical_name_hint",
        "api_key",
        "authorization",
        "request_spec",
        "raw_response",
        "output_parsed",
        "instructions",
        "secret",
    }
)
_TELEMETRY_KEYS = frozenset(
    {
        "request_id",
        "provider",
        "model",
        "prompt_version",
        "attempt_count",
        "outcome_category",
        "input_tokens",
        "output_tokens",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)bearer\s+\S+"),
)

ScenarioTrace = tuple[Scenario, ArchitectureIntent | Exception, Sequence[EvalResult]]


class AdapterTelemetryCapture(logging.Handler):
    """Copies only the already-safe adapter telemetry extras (counts,
    ids, outcome category). Never copies request text or response bodies.
    Attach to `iac_agent.intent.adapters` so any future sibling adapter
    logger propagates here without the runner naming a provider."""

    def __init__(self) -> None:
        super().__init__()
        self.by_request_id: dict[str, dict[str, object]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        payload: dict[str, object] = {}
        for key in _TELEMETRY_KEYS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        request_id = payload.get("request_id")
        if isinstance(request_id, str) and request_id:
            self.by_request_id[request_id] = payload


def normalize_intent_semantics(intent: ArchitectureIntent) -> dict[str, object]:
    """Closed-enum fields plus question presence/count — never free text."""
    return {
        "workload_type": intent.workload_type.value,
        "interaction_pattern": intent.interaction_pattern.value,
        "capabilities": sorted(c.value for c in intent.capabilities),
        "user_provided_hints": sorted(h.value for h in intent.user_provided_hints),
        "unresolved_questions_present": len(intent.unresolved_questions) > 0,
        "unresolved_questions_count": len(intent.unresolved_questions),
    }


def normalize_expected_semantics(expected: ExpectedOutcome) -> dict[str, object]:
    capabilities = None if expected.capabilities is None else sorted(expected.capabilities)
    hints = None if expected.user_provided_hints is None else sorted(expected.user_provided_hints)
    return {
        "workload_type": expected.workload_type,
        "interaction_pattern": expected.interaction_pattern,
        "capabilities": capabilities,
        "user_provided_hints": hints,
        "unresolved_questions_expected": expected.unresolved_questions_expected,
    }


def resolution_outcome(intent: ArchitectureIntent) -> str:
    return ArchitectureResolver().resolve(intent=intent, request_id=_EVAL_REQUEST_ID).outcome


def reference_resolution_outcome(scenario: Scenario) -> str | None:
    expected = scenario.expected
    if expected.workload_type is None:
        return None
    reference = ArchitectureIntent(
        workload_type=WorkloadType(expected.workload_type),
        interaction_pattern=InteractionPattern(expected.interaction_pattern or "unspecified"),
        capabilities=frozenset(Capability(c) for c in (expected.capabilities or ())),
    )
    return resolution_outcome(reference)


def sanitize_failure_message(message: str) -> str:
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized


def build_layer2_document(
    *,
    traces: Sequence[ScenarioTrace],
    dataset_path: str,
    run_metadata: Mapping[str, str] | None = None,
    telemetry_by_request_id: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    metadata = dict(run_metadata or {})
    telemetry = telemetry_by_request_id or {}
    results: list[dict[str, object]] = []
    for scenario, outcome, eval_results in traces:
        expected_normalized = normalize_expected_semantics(scenario.expected)
        if isinstance(outcome, ArchitectureIntent):
            actual_normalized: dict[str, object] | None = normalize_intent_semantics(outcome)
            actual_resolver = resolution_outcome(outcome)
        else:
            actual_normalized = None
            actual_resolver = None
        expected_resolver = reference_resolution_outcome(scenario)
        row_telemetry = dict(telemetry.get(f"layer2-{scenario.id}", {}))
        for eval_result in eval_results:
            results.append(
                _result_row(
                    eval_result=eval_result,
                    expected_normalized=expected_normalized,
                    actual_normalized=actual_normalized,
                    expected_resolver=expected_resolver,
                    actual_resolver=actual_resolver,
                    metadata=metadata,
                    row_telemetry=row_telemetry,
                )
            )

    run: dict[str, object] = {
        "dataset_path": dataset_path,
        "scenario_count": len(traces),
        "evaluation_count": len(results),
    }
    for key in ("provider", "model", "prompt_version"):
        value = metadata.get(key)
        if value is None:
            value = _first_telemetry_value(telemetry, key)
        if value is not None:
            run[key] = value

    document = {"run": run, "results": results}
    _validate_document(document)
    return document


def write_layer2_diagnostic(document: Mapping[str, Any], *, path: Path) -> Path:
    _validate_document(document)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def _result_row(
    *,
    eval_result: EvalResult,
    expected_normalized: dict[str, object],
    actual_normalized: dict[str, object] | None,
    expected_resolver: str | None,
    actual_resolver: str | None,
    metadata: Mapping[str, str],
    row_telemetry: Mapping[str, object],
) -> dict[str, object]:
    row: dict[str, object] = {
        "scenario_id": eval_result.scenario_id,
        "evaluator": eval_result.evaluator,
        "status": eval_result.status.value,
        "expected_normalized": expected_normalized,
        "actual_normalized": actual_normalized,
        "failure_message_sanitized": sanitize_failure_message(eval_result.message),
        "resolver_outcome_expected": expected_resolver,
        "resolver_outcome_actual": actual_resolver,
    }
    for key in ("provider", "model", "prompt_version"):
        value = row_telemetry.get(key, metadata.get(key))
        if value is not None:
            row[key] = value
    attempt_count = row_telemetry.get("attempt_count")
    if attempt_count is not None:
        row["attempt_count"] = attempt_count
    outcome_category = row_telemetry.get("outcome_category")
    if outcome_category is not None:
        row["outcome_category"] = outcome_category
    token_metadata = {
        key: row_telemetry[key] for key in _ALLOWED_TOKEN_KEYS if key in row_telemetry
    }
    if token_metadata:
        row["token_metadata"] = token_metadata
    return row


def _first_telemetry_value(
    telemetry: Mapping[str, Mapping[str, object]], key: str
) -> object | None:
    for payload in telemetry.values():
        if key in payload:
            return payload[key]
    return None


def _validate_document(document: Mapping[str, Any]) -> None:
    _reject_forbidden_keys(document)
    extra_top = set(document) - _ALLOWED_DOCUMENT_KEYS
    if extra_top:
        raise ValueError(f"diagnostic document has unknown keys: {sorted(extra_top)}")
    run = document.get("run")
    if not isinstance(run, Mapping):
        raise ValueError("diagnostic document is missing 'run'")
    extra_run = set(run) - _ALLOWED_RUN_KEYS
    if extra_run:
        raise ValueError(f"diagnostic run has unknown keys: {sorted(extra_run)}")
    results = document.get("results")
    if not isinstance(results, list):
        raise ValueError("diagnostic document is missing 'results'")
    for row in results:
        if not isinstance(row, Mapping):
            raise ValueError("diagnostic result row must be an object")
        extra_row = set(row) - _ALLOWED_RESULT_KEYS
        if extra_row:
            raise ValueError(f"forbidden or unknown diagnostic key: {sorted(extra_row)}")
        for nested_name in ("expected_normalized", "actual_normalized"):
            nested = row.get(nested_name)
            if nested is None:
                continue
            if not isinstance(nested, Mapping):
                raise ValueError(f"{nested_name} must be an object")
            extra_nested = set(nested) - _ALLOWED_NORMALIZED_KEYS
            if extra_nested:
                raise ValueError(f"forbidden or unknown normalized key: {sorted(extra_nested)}")
        tokens = row.get("token_metadata")
        if tokens is None:
            continue
        if not isinstance(tokens, Mapping):
            raise ValueError("token_metadata must be an object")
        extra_tokens = set(tokens) - _ALLOWED_TOKEN_KEYS
        if extra_tokens:
            raise ValueError(f"forbidden or unknown token_metadata key: {sorted(extra_tokens)}")


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _FORBIDDEN_KEYS)
        if forbidden:
            raise ValueError(f"forbidden diagnostic key: {forbidden[0]}")
        for nested in value.values():
            _reject_forbidden_keys(nested)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)

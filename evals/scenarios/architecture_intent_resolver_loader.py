"""Deterministic loader/validator for the architecture-intent-resolver
golden-scenario dataset (Batch 21, Task 7).

Mirrors `evals.scenarios.loader`'s discipline exactly: the dataset is a
version-controlled, human-readable JSON product artifact, and this
loader enforces its schema explicitly and fails closed on any
structural problem — malformed scenarios are never silently skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_SCENARIO_KEYS = ("id", "description", "input", "expected")

_VALID_OUTCOMES = ("resolved", "clarification_required", "unsupported")


class DatasetError(Exception):
    """Raised when the golden dataset file is malformed or structurally
    invalid. Never raised for a legitimate scenario outcome — only for
    problems with the dataset file itself."""


@dataclass(frozen=True)
class ExpectedOutcome:
    """The expected behavior for one scenario. Only `schema_valid` is
    guaranteed meaningful for a schema-invalid scenario; every other
    field is `None` in that case, since no `ArchitectureIntent` is ever
    constructed to compare them against."""

    schema_valid: bool
    outcome: str | None = None
    matched_pattern: str | None = None
    resolved_type: str | None = None
    clarification_field: str | None = None
    clarification_reason: str | None = None
    unsupported_reason: str | None = None
    expected_name: str | None = None
    expected_name_prefix: str | None = None


@dataclass(frozen=True)
class Scenario:
    """One golden scenario: a raw payload and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: ExpectedOutcome


def load_architecture_intent_resolver_golden_dataset(path: Path | str) -> tuple[Scenario, ...]:
    """Load and validate the golden dataset at `path`. Scenarios are
    returned in exactly the order they appear in the dataset file."""
    file_path = Path(path)
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetError(f"could not read dataset file: {file_path}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DatasetError(f"dataset is not valid JSON: {file_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise DatasetError(f"dataset root must be a JSON object: {file_path}")

    version = payload.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise DatasetError(f"dataset 'version' must be an integer: {file_path}")

    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise DatasetError(f"dataset 'scenarios' must be a non-empty list: {file_path}")

    scenarios: list[Scenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> Scenario:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenarios[{index}] must be an object")

    for key in _REQUIRED_SCENARIO_KEYS:
        if key not in raw:
            raise DatasetError(f"scenarios[{index}] is missing required key {key!r}")

    scenario_id = raw["id"]
    if not isinstance(scenario_id, str) or not scenario_id:
        raise DatasetError(f"scenarios[{index}].id must be a non-empty string")

    description = raw["description"]
    if not isinstance(description, str):
        raise DatasetError(f"scenario {scenario_id!r}.description must be a string")

    scenario_input = raw["input"]
    if not isinstance(scenario_input, dict):
        raise DatasetError(f"scenario {scenario_id!r}.input must be an object")

    expected = _parse_expected(scenario_id, raw["expected"])

    return Scenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> ExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "schema_valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing 'schema_valid'")
    schema_valid = raw["schema_valid"]
    if not isinstance(schema_valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.schema_valid must be a boolean")

    if not schema_valid:
        return ExpectedOutcome(schema_valid=False)

    outcome = raw.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.outcome must be one of {_VALID_OUTCOMES} "
            "when schema_valid is true"
        )

    if outcome == "resolved":
        matched_pattern = raw.get("matched_pattern")
        resolved_type = raw.get("resolved_type")
        if not isinstance(matched_pattern, str) or not isinstance(resolved_type, str):
            raise DatasetError(
                f"scenario {scenario_id!r}: a 'resolved' outcome requires string "
                "'matched_pattern' and 'resolved_type'"
            )
        return ExpectedOutcome(
            schema_valid=True,
            outcome=outcome,
            matched_pattern=matched_pattern,
            resolved_type=resolved_type,
            expected_name=raw.get("expected_name"),
            expected_name_prefix=raw.get("expected_name_prefix"),
        )

    if outcome == "clarification_required":
        clarification_field = raw.get("clarification_field")
        clarification_reason = raw.get("clarification_reason")
        if not isinstance(clarification_field, str) or not isinstance(clarification_reason, str):
            raise DatasetError(
                f"scenario {scenario_id!r}: a 'clarification_required' outcome requires "
                "string 'clarification_field' and 'clarification_reason'"
            )
        return ExpectedOutcome(
            schema_valid=True,
            outcome=outcome,
            clarification_field=clarification_field,
            clarification_reason=clarification_reason,
        )

    unsupported_reason = raw.get("unsupported_reason")
    if not isinstance(unsupported_reason, str):
        raise DatasetError(
            f"scenario {scenario_id!r}: an 'unsupported' outcome requires string "
            "'unsupported_reason'"
        )
    return ExpectedOutcome(
        schema_valid=True, outcome=outcome, unsupported_reason=unsupported_reason
    )

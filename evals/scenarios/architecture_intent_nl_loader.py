"""Deterministic loader/validator for the Layer 2 (real-model) natural-
language golden-scenario dataset (Batch 23, Task 7/8).

Mirrors `evals.scenarios.architecture_intent_resolver_loader`'s
discipline exactly — the dataset is a version-controlled, human-
readable JSON product artifact, and this loader enforces its schema
explicitly and fails closed on any structural problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_SCENARIO_KEYS = ("id", "description", "natural_language_request", "expected")
_VALID_WORKLOAD_TYPES = ("api", "worker", "storage", "unspecified")
_VALID_INTERACTION_PATTERNS = ("synchronous", "asynchronous", "unspecified")


class DatasetError(Exception):
    """Raised when the golden dataset file is malformed or structurally
    invalid. Never raised for a legitimate scenario outcome — only for
    problems with the dataset file itself."""


@dataclass(frozen=True)
class ExpectedOutcome:
    """The expected semantic behavior for one scenario. Only
    `schema_valid` is guaranteed meaningful for a schema-invalid
    scenario; every semantic field below is optional since not every
    scenario asserts every dimension (e.g. a genuinely ambiguous
    scenario asserts `workload_type="unspecified"` and nothing more)."""

    schema_valid: bool
    workload_type: str | None = None
    interaction_pattern: str | None = None
    capabilities: tuple[str, ...] | None = None
    user_provided_hints: tuple[str, ...] | None = None
    unresolved_questions_expected: bool | None = None


@dataclass(frozen=True)
class Scenario:
    """One Layer 2 golden scenario: a natural-language request and the
    semantic behavior expected of the interpreter's output."""

    id: str
    description: str
    natural_language_request: str
    expected: ExpectedOutcome


def load_architecture_intent_nl_golden_dataset(path: Path | str) -> tuple[Scenario, ...]:
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

    natural_language_request = raw["natural_language_request"]
    if not isinstance(natural_language_request, str) or not natural_language_request:
        raise DatasetError(
            f"scenario {scenario_id!r}.natural_language_request must be a non-empty string"
        )

    expected = _parse_expected(scenario_id, raw["expected"])

    return Scenario(
        id=scenario_id,
        description=description,
        natural_language_request=natural_language_request,
        expected=expected,
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

    workload_type = raw.get("workload_type")
    if workload_type is not None and workload_type not in _VALID_WORKLOAD_TYPES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.workload_type must be one of "
            f"{_VALID_WORKLOAD_TYPES}"
        )

    interaction_pattern = raw.get("interaction_pattern")
    if interaction_pattern is not None and interaction_pattern not in _VALID_INTERACTION_PATTERNS:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.interaction_pattern must be one of "
            f"{_VALID_INTERACTION_PATTERNS}"
        )

    raw_capabilities = raw.get("capabilities")
    capabilities = tuple(raw_capabilities) if raw_capabilities is not None else None

    raw_hints = raw.get("user_provided_hints")
    user_provided_hints = tuple(raw_hints) if raw_hints is not None else None

    unresolved_questions_expected = raw.get("unresolved_questions_expected")
    if unresolved_questions_expected is not None and not isinstance(
        unresolved_questions_expected, bool
    ):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.unresolved_questions_expected must be a boolean"
        )

    return ExpectedOutcome(
        schema_valid=True,
        workload_type=workload_type,
        interaction_pattern=interaction_pattern,
        capabilities=capabilities,
        user_provided_hints=user_provided_hints,
        unresolved_questions_expected=unresolved_questions_expected,
    )

"""Deterministic loader/validator for the DynamoDB golden-scenario
dataset (Batch 17).

Mirrors `evals.scenarios.s3_loader` exactly in structure and validation
discipline, with its own schema shaped around `DynamoDBResourceSpec`'s
fields — a deliberately separate module rather than a generalized/
parameterized loader, since the datasets' `expected` schemas share no
fields beyond `valid`/`overall_security_status`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.scenarios.loader import DatasetError

_REQUIRED_SCENARIO_KEYS = ("id", "description", "input", "expected")

#: Required only when expected.valid is True — an invalid scenario
#: expects nothing beyond "construction was rejected", since no spec
#: ever exists to check these fields against.
_REQUIRED_EXPECTED_KEYS_WHEN_VALID = (
    "table_name",
    "partition_key_name",
    "partition_key_type",
    "point_in_time_recovery",
    "deletion_protection",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")
_VALID_KEY_TYPES = ("S", "N", "B")


@dataclass(frozen=True)
class DynamoDBExpectedOutcome:
    """The expected behavior for one DynamoDB scenario.

    Only ``valid`` is guaranteed to be meaningful for an
    expected-invalid scenario; every other field is ``None`` in that
    case because no spec is ever constructed to compare them against.
    """

    valid: bool
    table_name: str | None = None
    partition_key_name: str | None = None
    partition_key_type: str | None = None
    sort_key_name: str | None = None
    sort_key_type: str | None = None
    point_in_time_recovery: bool | None = None
    deletion_protection: bool | None = None
    overall_security_status: str | None = None


@dataclass(frozen=True)
class DynamoDBScenario:
    """One golden DynamoDB scenario: a request and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: DynamoDBExpectedOutcome


def load_dynamodb_golden_dataset(path: Path | str) -> tuple[DynamoDBScenario, ...]:
    """Load and validate the DynamoDB golden dataset at `path`.

    Scenarios are returned in exactly the order they appear in the
    dataset file — the runner relies on this deterministic ordering;
    nothing here re-sorts by scenario id.
    """
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

    scenarios: list[DynamoDBScenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> DynamoDBScenario:
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

    return DynamoDBScenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> DynamoDBExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return DynamoDBExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    table_name = raw["table_name"]
    if not isinstance(table_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.table_name must be a string")

    partition_key_name = raw["partition_key_name"]
    if not isinstance(partition_key_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.partition_key_name must be a string")

    partition_key_type = raw["partition_key_type"]
    if partition_key_type not in _VALID_KEY_TYPES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.partition_key_type must be one of "
            f"{_VALID_KEY_TYPES}"
        )

    sort_key_name = raw.get("sort_key_name")
    if sort_key_name is not None and not isinstance(sort_key_name, str):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.sort_key_name must be a string or null"
        )

    sort_key_type = raw.get("sort_key_type")
    if sort_key_type is not None and sort_key_type not in _VALID_KEY_TYPES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.sort_key_type must be one of "
            f"{_VALID_KEY_TYPES} or null"
        )

    point_in_time_recovery = raw["point_in_time_recovery"]
    if not isinstance(point_in_time_recovery, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.point_in_time_recovery must be a boolean"
        )

    deletion_protection = raw["deletion_protection"]
    if not isinstance(deletion_protection, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.deletion_protection must be a boolean"
        )

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    return DynamoDBExpectedOutcome(
        valid=True,
        table_name=table_name,
        partition_key_name=partition_key_name,
        partition_key_type=partition_key_type,
        sort_key_name=sort_key_name,
        sort_key_type=sort_key_type,
        point_in_time_recovery=point_in_time_recovery,
        deletion_protection=deletion_protection,
        overall_security_status=overall_security_status,
    )

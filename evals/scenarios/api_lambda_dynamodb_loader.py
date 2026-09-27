"""Deterministic loader/validator for the api_lambda_dynamodb golden-
scenario dataset (Batch 26).

Mirrors `evals.scenarios.api_lambda_loader` in structure, extended with
`serverless_worker_loader`'s table-related expected fields
(`table_name`, `point_in_time_recovery`, `deletion_protection`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.scenarios.loader import DatasetError

_REQUIRED_SCENARIO_KEYS = ("id", "description", "input", "expected")

_REQUIRED_EXPECTED_KEYS_WHEN_VALID = (
    "name",
    "api_name",
    "function_name",
    "route_key",
    "table_name",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")


@dataclass(frozen=True)
class ApiLambdaDynamoDbExpectedOutcome:
    """The expected behavior for one api_lambda_dynamodb scenario.

    Only `valid` is guaranteed to be meaningful for an expected-invalid
    scenario; every other field is `None` in that case because no spec
    is ever constructed to compare them against.
    """

    valid: bool
    name: str | None = None
    api_name: str | None = None
    function_name: str | None = None
    route_key: str | None = None
    table_name: str | None = None
    tracing_mode: str | None = None
    reserved_concurrency: int | None = None
    point_in_time_recovery: bool | None = None
    deletion_protection: bool | None = None
    overall_security_status: str | None = None


@dataclass(frozen=True)
class ApiLambdaDynamoDbScenario:
    """One golden api_lambda_dynamodb scenario: a request and the
    behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: ApiLambdaDynamoDbExpectedOutcome


def load_api_lambda_dynamodb_golden_dataset(
    path: Path | str,
) -> tuple[ApiLambdaDynamoDbScenario, ...]:
    """Load and validate the api_lambda_dynamodb golden dataset at
    `path`.

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

    scenarios: list[ApiLambdaDynamoDbScenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> ApiLambdaDynamoDbScenario:
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

    return ApiLambdaDynamoDbScenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> ApiLambdaDynamoDbExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return ApiLambdaDynamoDbExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    name = raw["name"]
    if not isinstance(name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.name must be a string")

    api_name = raw["api_name"]
    if not isinstance(api_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.api_name must be a string")

    function_name = raw["function_name"]
    if not isinstance(function_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.function_name must be a string")

    route_key = raw["route_key"]
    if not isinstance(route_key, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.route_key must be a string")

    table_name = raw["table_name"]
    if not isinstance(table_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.table_name must be a string")

    tracing_mode = raw.get("tracing_mode")
    if tracing_mode is not None and not isinstance(tracing_mode, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.tracing_mode must be a string")

    reserved_concurrency = raw.get("reserved_concurrency")
    if reserved_concurrency is not None and (
        not isinstance(reserved_concurrency, int) or isinstance(reserved_concurrency, bool)
    ):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.reserved_concurrency must be an integer or null"
        )

    point_in_time_recovery = raw.get("point_in_time_recovery")
    if point_in_time_recovery is not None and not isinstance(point_in_time_recovery, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.point_in_time_recovery must be a boolean"
        )

    deletion_protection = raw.get("deletion_protection")
    if deletion_protection is not None and not isinstance(deletion_protection, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.deletion_protection must be a boolean"
        )

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    return ApiLambdaDynamoDbExpectedOutcome(
        valid=True,
        name=name,
        api_name=api_name,
        function_name=function_name,
        route_key=route_key,
        table_name=table_name,
        tracing_mode=tracing_mode,
        reserved_concurrency=reserved_concurrency,
        point_in_time_recovery=point_in_time_recovery,
        deletion_protection=deletion_protection,
        overall_security_status=overall_security_status,
    )

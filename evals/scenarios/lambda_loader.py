"""Deterministic loader/validator for the Lambda golden-scenario
dataset (Batch 18).

Mirrors `evals.scenarios.dynamodb_loader` exactly in structure and
validation discipline, with its own schema shaped around
`LambdaResourceSpec`'s fields — a deliberately separate module rather
than a generalized/parameterized loader, since the datasets' `expected`
schemas share no fields beyond `valid`/`overall_security_status`.
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
    "function_name",
    "handler",
    "architecture",
    "memory_size_mb",
    "timeout_seconds",
    "tracing_mode",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")
_VALID_ARCHITECTURES = ("x86_64", "arm64")
_VALID_TRACING_MODES = ("Active", "PassThrough")


@dataclass(frozen=True)
class LambdaExpectedOutcome:
    """The expected behavior for one Lambda scenario.

    Only ``valid`` is guaranteed to be meaningful for an
    expected-invalid scenario; every other field is ``None`` in that
    case because no spec is ever constructed to compare them against.
    """

    valid: bool
    function_name: str | None = None
    handler: str | None = None
    architecture: str | None = None
    memory_size_mb: int | None = None
    timeout_seconds: int | None = None
    reserved_concurrency: int | None = None
    tracing_mode: str | None = None
    overall_security_status: str | None = None


@dataclass(frozen=True)
class LambdaScenario:
    """One golden Lambda scenario: a request and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: LambdaExpectedOutcome


def load_lambda_golden_dataset(path: Path | str) -> tuple[LambdaScenario, ...]:
    """Load and validate the Lambda golden dataset at `path`.

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

    scenarios: list[LambdaScenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> LambdaScenario:
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

    return LambdaScenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> LambdaExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return LambdaExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    function_name = raw["function_name"]
    if not isinstance(function_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.function_name must be a string")

    handler = raw["handler"]
    if not isinstance(handler, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.handler must be a string")

    architecture = raw["architecture"]
    if architecture not in _VALID_ARCHITECTURES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.architecture must be one of {_VALID_ARCHITECTURES}"
        )

    memory_size_mb = raw["memory_size_mb"]
    if not isinstance(memory_size_mb, int) or isinstance(memory_size_mb, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.memory_size_mb must be an integer")

    timeout_seconds = raw["timeout_seconds"]
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.timeout_seconds must be an integer")

    reserved_concurrency = raw.get("reserved_concurrency")
    if reserved_concurrency is not None and (
        not isinstance(reserved_concurrency, int) or isinstance(reserved_concurrency, bool)
    ):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.reserved_concurrency must be an integer or null"
        )

    tracing_mode = raw["tracing_mode"]
    if tracing_mode not in _VALID_TRACING_MODES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.tracing_mode must be one of {_VALID_TRACING_MODES}"
        )

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    return LambdaExpectedOutcome(
        valid=True,
        function_name=function_name,
        handler=handler,
        architecture=architecture,
        memory_size_mb=memory_size_mb,
        timeout_seconds=timeout_seconds,
        reserved_concurrency=reserved_concurrency,
        tracing_mode=tracing_mode,
        overall_security_status=overall_security_status,
    )

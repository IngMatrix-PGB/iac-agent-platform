"""Deterministic loader/validator for the SQS golden-scenario dataset.

The dataset is a version-controlled, human-readable JSON product
artifact (not Python code) so it can also be consumed by CI, reporting
tools, or a future UI without importing this package. This loader
enforces the schema explicitly and fails closed on any structural
problem — malformed scenarios are never silently skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_SCENARIO_KEYS = ("id", "description", "input", "expected")

#: Required only when expected.valid is True — an invalid scenario
#: expects nothing beyond "construction was rejected", since no spec
#: ever exists to check these fields against (see loader/runner).
_REQUIRED_EXPECTED_KEYS_WHEN_VALID = (
    "queue_name",
    "fifo",
    "dlq_enabled",
    "encryption_enabled",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")


class DatasetError(Exception):
    """Raised when the golden dataset file is malformed or structurally
    invalid. Never raised for a legitimate scenario outcome — only for
    problems with the dataset file itself."""


@dataclass(frozen=True)
class ExpectedOutcome:
    """The expected behavior for one scenario.

    Only ``valid`` is guaranteed to be meaningful for an
    expected-invalid scenario; every other field is ``None`` in that
    case because no spec is ever constructed to compare them against.
    """

    valid: bool
    queue_name: str | None = None
    fifo: bool | None = None
    dlq_enabled: bool | None = None
    encryption_enabled: bool | None = None
    kms_key_id: str | None = None
    overall_security_status: str | None = None


@dataclass(frozen=True)
class Scenario:
    """One golden scenario: a request and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: ExpectedOutcome


def load_sqs_golden_dataset(path: Path | str) -> tuple[Scenario, ...]:
    """Load and validate the golden dataset at `path`.

    Scenarios are returned in exactly the order they appear in the
    dataset file — this is the documented deterministic ordering the
    runner relies on; nothing here re-sorts by scenario id.
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

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return ExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    queue_name = raw["queue_name"]
    if not isinstance(queue_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.queue_name must be a string")

    fifo = raw["fifo"]
    if not isinstance(fifo, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.fifo must be a boolean")

    dlq_enabled = raw["dlq_enabled"]
    if not isinstance(dlq_enabled, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.dlq_enabled must be a boolean")

    encryption_enabled = raw["encryption_enabled"]
    if not isinstance(encryption_enabled, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.encryption_enabled must be a boolean"
        )

    kms_key_id = raw.get("kms_key_id")
    if kms_key_id is not None and not isinstance(kms_key_id, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.kms_key_id must be a string or null")

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    return ExpectedOutcome(
        valid=True,
        queue_name=queue_name,
        fifo=fifo,
        dlq_enabled=dlq_enabled,
        encryption_enabled=encryption_enabled,
        kms_key_id=kms_key_id,
        overall_security_status=overall_security_status,
    )

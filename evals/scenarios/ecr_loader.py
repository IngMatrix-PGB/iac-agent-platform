"""Deterministic loader/validator for the ECR golden-scenario dataset.

A separate module from the S3 loader: ECR's expected fields are the
repository name, tag mutability, scan-on-push, and encryption flag.
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
    "image_tag_mutability",
    "scan_on_push",
    "encryption_enabled",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")
_VALID_MUTABILITY = ("MUTABLE", "IMMUTABLE")


@dataclass(frozen=True)
class EcrExpectedOutcome:
    """Expected behavior for one ECR scenario.

    Only ``valid`` is meaningful when construction is expected to fail.
    ``policy_id`` is set when the scenario must show a specific finding
    at the overall security status.
    """

    valid: bool
    name: str | None = None
    image_tag_mutability: str | None = None
    scan_on_push: bool | None = None
    encryption_enabled: bool | None = None
    overall_security_status: str | None = None
    policy_id: str | None = None


@dataclass(frozen=True)
class EcrScenario:
    """One golden ECR scenario: a request and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: EcrExpectedOutcome


def load_ecr_golden_dataset(path: Path | str) -> tuple[EcrScenario, ...]:
    """Load and validate the ECR golden dataset at `path`.

    Scenarios are returned in dataset order. Nothing here re-sorts by id.
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

    scenarios: list[EcrScenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> EcrScenario:
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
    return EcrScenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> EcrExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return EcrExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    name = raw["name"]
    if not isinstance(name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.name must be a string")

    image_tag_mutability = raw["image_tag_mutability"]
    if image_tag_mutability not in _VALID_MUTABILITY:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.image_tag_mutability must be one of "
            f"{_VALID_MUTABILITY}"
        )

    scan_on_push = raw["scan_on_push"]
    if not isinstance(scan_on_push, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.scan_on_push must be a boolean")

    encryption_enabled = raw["encryption_enabled"]
    if not isinstance(encryption_enabled, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.encryption_enabled must be a boolean"
        )

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    policy_id = raw.get("policy_id")
    if policy_id is not None and (not isinstance(policy_id, str) or not policy_id):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.policy_id must be a non-empty string or omitted"
        )

    return EcrExpectedOutcome(
        valid=True,
        name=name,
        image_tag_mutability=image_tag_mutability,
        scan_on_push=scan_on_push,
        encryption_enabled=encryption_enabled,
        overall_security_status=overall_security_status,
        policy_id=policy_id,
    )

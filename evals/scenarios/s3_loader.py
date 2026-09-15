"""Deterministic loader/validator for the S3 golden-scenario dataset.

Mirrors `evals.scenarios.loader` (the SQS loader) exactly in structure
and validation discipline, with its own schema shaped around
`S3ResourceSpec`'s fields — a deliberately separate module rather than
a generalized/parameterized loader, since the two datasets' `expected`
schemas share no fields at all beyond `valid` and
`overall_security_status` (see `iac_agent.providers.aws.s3.contract`
vs `iac_agent.providers.aws.sqs.contract`).
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
    "bucket_name",
    "versioning",
    "encryption_enabled",
    "block_public_access",
    "overall_security_status",
)

_VALID_SECURITY_STATUSES = ("pass", "warn", "block")


@dataclass(frozen=True)
class S3ExpectedOutcome:
    """The expected behavior for one S3 scenario.

    Only ``valid`` is guaranteed to be meaningful for an
    expected-invalid scenario; every other field is ``None`` in that
    case because no spec is ever constructed to compare them against.
    """

    valid: bool
    bucket_name: str | None = None
    versioning: bool | None = None
    encryption_enabled: bool | None = None
    kms_key_id: str | None = None
    block_public_access: bool | None = None
    overall_security_status: str | None = None


@dataclass(frozen=True)
class S3Scenario:
    """One golden S3 scenario: a request and the behavior expected of it."""

    id: str
    description: str
    input: dict[str, Any]
    expected: S3ExpectedOutcome


def load_s3_golden_dataset(path: Path | str) -> tuple[S3Scenario, ...]:
    """Load and validate the S3 golden dataset at `path`.

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

    scenarios: list[S3Scenario] = []
    seen_ids: set[str] = set()
    for index, raw_scenario in enumerate(raw_scenarios):
        scenario = _parse_scenario(index, raw_scenario)
        if scenario.id in seen_ids:
            raise DatasetError(f"duplicate scenario id: {scenario.id!r}")
        seen_ids.add(scenario.id)
        scenarios.append(scenario)

    return tuple(scenarios)


def _parse_scenario(index: int, raw: Any) -> S3Scenario:
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

    return S3Scenario(
        id=scenario_id, description=description, input=scenario_input, expected=expected
    )


def _parse_expected(scenario_id: str, raw: Any) -> S3ExpectedOutcome:
    if not isinstance(raw, dict):
        raise DatasetError(f"scenario {scenario_id!r}.expected must be an object")

    if "valid" not in raw:
        raise DatasetError(f"scenario {scenario_id!r}.expected is missing required key 'valid'")
    valid = raw["valid"]
    if not isinstance(valid, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.valid must be a boolean")

    if not valid:
        return S3ExpectedOutcome(valid=False)

    missing = [key for key in _REQUIRED_EXPECTED_KEYS_WHEN_VALID if key not in raw]
    if missing:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected is missing required key(s) for a valid "
            f"scenario: {missing}"
        )

    bucket_name = raw["bucket_name"]
    if not isinstance(bucket_name, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.bucket_name must be a string")

    versioning = raw["versioning"]
    if not isinstance(versioning, bool):
        raise DatasetError(f"scenario {scenario_id!r}.expected.versioning must be a boolean")

    encryption_enabled = raw["encryption_enabled"]
    if not isinstance(encryption_enabled, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.encryption_enabled must be a boolean"
        )

    kms_key_id = raw.get("kms_key_id")
    if kms_key_id is not None and not isinstance(kms_key_id, str):
        raise DatasetError(f"scenario {scenario_id!r}.expected.kms_key_id must be a string or null")

    block_public_access = raw["block_public_access"]
    if not isinstance(block_public_access, bool):
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.block_public_access must be a boolean"
        )

    overall_security_status = raw["overall_security_status"]
    if overall_security_status not in _VALID_SECURITY_STATUSES:
        raise DatasetError(
            f"scenario {scenario_id!r}.expected.overall_security_status must be one of "
            f"{_VALID_SECURITY_STATUSES}"
        )

    return S3ExpectedOutcome(
        valid=True,
        bucket_name=bucket_name,
        versioning=versioning,
        encryption_enabled=encryption_enabled,
        kms_key_id=kms_key_id,
        block_public_access=block_public_access,
        overall_security_status=overall_security_status,
    )

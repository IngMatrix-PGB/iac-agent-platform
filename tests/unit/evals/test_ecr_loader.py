"""Unit tests for the ECR golden-dataset loader (Batch 27).

Mirrors the validation discipline of the other resource loaders:
duplicate-id rejection and required-key enforcement for a valid scenario.
"""

from __future__ import annotations

import json

import pytest

from evals.scenarios.ecr_loader import load_ecr_golden_dataset
from evals.scenarios.loader import DatasetError


def _write(tmp_path, payload) -> str:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _valid_scenario(scenario_id="s1"):
    return {
        "id": scenario_id,
        "description": "d",
        "input": {"name": "orders"},
        "expected": {
            "valid": True,
            "name": "orders",
            "image_tag_mutability": "IMMUTABLE",
            "scan_on_push": True,
            "encryption_enabled": True,
            "overall_security_status": "pass",
        },
    }


def test_loads_a_minimal_valid_dataset(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": [_valid_scenario()]})
    scenarios = load_ecr_golden_dataset(path)
    assert len(scenarios) == 1
    assert scenarios[0].id == "s1"
    assert scenarios[0].expected.name == "orders"
    assert scenarios[0].expected.image_tag_mutability == "IMMUTABLE"


def test_loads_an_invalid_scenario_with_no_expected_fields_required(tmp_path):
    scenario = {"id": "s1", "description": "d", "input": {}, "expected": {"valid": False}}
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario]})
    scenarios = load_ecr_golden_dataset(path)
    assert scenarios[0].expected.valid is False
    assert scenarios[0].expected.name is None


def test_duplicate_scenario_id_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"version": 1, "scenarios": [_valid_scenario("dup"), _valid_scenario("dup")]},
    )
    with pytest.raises(DatasetError, match="duplicate scenario id"):
        load_ecr_golden_dataset(path)


def test_valid_scenario_missing_a_required_expected_key_is_rejected(tmp_path):
    scenario = _valid_scenario()
    del scenario["expected"]["scan_on_push"]
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario]})
    with pytest.raises(DatasetError, match="missing required key"):
        load_ecr_golden_dataset(path)

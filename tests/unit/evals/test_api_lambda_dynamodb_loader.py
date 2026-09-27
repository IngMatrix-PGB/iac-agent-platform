"""Unit tests for the api_lambda_dynamodb golden-dataset loader (Batch
26). Mirrors the validation discipline of every other composition's
loader test — malformed dataset rejection, duplicate-id rejection,
required-key-when-valid enforcement.
"""

from __future__ import annotations

import json

import pytest

from evals.scenarios.api_lambda_dynamodb_loader import load_api_lambda_dynamodb_golden_dataset
from evals.scenarios.loader import DatasetError


def _write(tmp_path, payload) -> str:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _valid_scenario(scenario_id="s1"):
    return {
        "id": scenario_id,
        "description": "d",
        "input": {"name": "x"},
        "expected": {
            "valid": True,
            "name": "x",
            "api_name": "x-api",
            "function_name": "x-fn",
            "route_key": "POST /x",
            "table_name": "x-table",
            "overall_security_status": "pass",
        },
    }


def test_loads_a_minimal_valid_dataset(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": [_valid_scenario()]})
    scenarios = load_api_lambda_dynamodb_golden_dataset(path)
    assert len(scenarios) == 1
    assert scenarios[0].id == "s1"
    assert scenarios[0].expected.table_name == "x-table"


def test_loads_an_invalid_scenario_with_no_expected_fields_required(tmp_path):
    scenario = {"id": "s1", "description": "d", "input": {}, "expected": {"valid": False}}
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario]})
    scenarios = load_api_lambda_dynamodb_golden_dataset(path)
    assert scenarios[0].expected.valid is False
    assert scenarios[0].expected.table_name is None


def test_missing_dataset_file_is_rejected(tmp_path):
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(tmp_path / "does-not-exist.json")


def test_malformed_json_is_rejected(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text("{not valid json")
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(str(path))


def test_non_object_root_is_rejected(tmp_path):
    path = _write(tmp_path, [1, 2, 3])
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(path)


def test_missing_version_is_rejected(tmp_path):
    path = _write(tmp_path, {"scenarios": [_valid_scenario()]})
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(path)


def test_empty_scenarios_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": []})
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(path)


def test_duplicate_scenario_id_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        {"version": 1, "scenarios": [_valid_scenario("dup"), _valid_scenario("dup")]},
    )
    with pytest.raises(DatasetError, match="duplicate scenario id"):
        load_api_lambda_dynamodb_golden_dataset(path)


def test_valid_scenario_missing_a_required_expected_key_is_rejected(tmp_path):
    scenario = _valid_scenario()
    del scenario["expected"]["table_name"]
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario]})
    with pytest.raises(DatasetError, match="missing required key"):
        load_api_lambda_dynamodb_golden_dataset(path)


def test_invalid_overall_security_status_is_rejected(tmp_path):
    scenario = _valid_scenario()
    scenario["expected"]["overall_security_status"] = "not-a-status"
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario]})
    with pytest.raises(DatasetError):
        load_api_lambda_dynamodb_golden_dataset(path)

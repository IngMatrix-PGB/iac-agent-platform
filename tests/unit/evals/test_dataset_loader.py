"""Unit tests for the golden-scenario dataset loader."""

from __future__ import annotations

import json

import pytest

from evals.scenarios.loader import DatasetError, Scenario, load_sqs_golden_dataset
from evals.scenarios.runner import DEFAULT_DATASET_PATH

_VALID_SCENARIO = {
    "id": "s1",
    "description": "d",
    "input": {"name": "order-events"},
    "expected": {
        "valid": True,
        "queue_name": "order-events",
        "fifo": False,
        "dlq_enabled": True,
        "encryption_enabled": True,
        "kms_key_id": None,
        "overall_security_status": "pass",
    },
}

_INVALID_SCENARIO = {
    "id": "s2",
    "description": "d2",
    "input": {"name": "orders", "fifo": True},
    "expected": {"valid": False},
}


def _write(tmp_path, payload) -> str:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_real_dataset_loads_required_eight_or_more_scenarios():
    scenarios = load_sqs_golden_dataset(DEFAULT_DATASET_PATH)
    ids = {s.id for s in scenarios}
    required = {
        "basic_standard_queue",
        "encrypted_queue_with_dlq",
        "fifo_queue",
        "invalid_fifo_name_combination",
        "invalid_message_retention",
        "attempted_encryption_disable",
        "dlq_disabled_warn",
        "secure_default_queue_pass",
    }
    assert required.issubset(ids)
    assert len(scenarios) >= 8


def test_loaded_scenario_is_typed():
    scenarios = load_sqs_golden_dataset(DEFAULT_DATASET_PATH)
    assert all(isinstance(s, Scenario) for s in scenarios)


def test_duplicate_scenario_id_is_rejected(tmp_path):
    payload = {"version": 1, "scenarios": [_VALID_SCENARIO, dict(_VALID_SCENARIO)]}
    path = _write(tmp_path, payload)
    with pytest.raises(DatasetError, match="duplicate"):
        load_sqs_golden_dataset(path)


def test_malformed_json_is_rejected(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text("not json {{{", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        load_sqs_golden_dataset(path)


def test_missing_scenario_id_is_rejected(tmp_path):
    broken = {k: v for k, v in _VALID_SCENARIO.items() if k != "id"}
    path = _write(tmp_path, {"version": 1, "scenarios": [broken]})
    with pytest.raises(DatasetError, match="id"):
        load_sqs_golden_dataset(path)


def test_missing_scenario_input_is_rejected(tmp_path):
    broken = {k: v for k, v in _VALID_SCENARIO.items() if k != "input"}
    path = _write(tmp_path, {"version": 1, "scenarios": [broken]})
    with pytest.raises(DatasetError, match="input"):
        load_sqs_golden_dataset(path)


def test_missing_scenario_expected_is_rejected(tmp_path):
    broken = {k: v for k, v in _VALID_SCENARIO.items() if k != "expected"}
    path = _write(tmp_path, {"version": 1, "scenarios": [broken]})
    with pytest.raises(DatasetError, match="expected"):
        load_sqs_golden_dataset(path)


def test_expected_valid_wrong_type_is_rejected(tmp_path):
    broken = dict(_VALID_SCENARIO)
    broken["expected"] = dict(broken["expected"])
    broken["expected"]["valid"] = "yes"
    path = _write(tmp_path, {"version": 1, "scenarios": [broken]})
    with pytest.raises(DatasetError, match="valid"):
        load_sqs_golden_dataset(path)


def test_missing_required_field_for_valid_scenario_is_rejected(tmp_path):
    broken = dict(_VALID_SCENARIO)
    broken["expected"] = {k: v for k, v in broken["expected"].items() if k != "fifo"}
    path = _write(tmp_path, {"version": 1, "scenarios": [broken]})
    with pytest.raises(DatasetError, match="fifo"):
        load_sqs_golden_dataset(path)


def test_invalid_scenario_does_not_require_extra_expected_fields(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": [_INVALID_SCENARIO]})
    scenarios = load_sqs_golden_dataset(path)
    assert scenarios[0].expected.valid is False
    assert scenarios[0].expected.queue_name is None


def test_non_object_scenario_entry_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": ["not-an-object"]})
    with pytest.raises(DatasetError, match="object"):
        load_sqs_golden_dataset(path)


def test_missing_version_is_rejected(tmp_path):
    path = _write(tmp_path, {"scenarios": [_VALID_SCENARIO]})
    with pytest.raises(DatasetError, match="version"):
        load_sqs_golden_dataset(path)


def test_empty_scenarios_list_is_rejected(tmp_path):
    path = _write(tmp_path, {"version": 1, "scenarios": []})
    with pytest.raises(DatasetError, match="non-empty"):
        load_sqs_golden_dataset(path)


def test_dataset_order_is_preserved_not_resorted(tmp_path):
    scenario_z = dict(_VALID_SCENARIO)
    scenario_z["id"] = "zzz_last"
    scenario_a = dict(_VALID_SCENARIO)
    scenario_a["id"] = "aaa_first"
    path = _write(tmp_path, {"version": 1, "scenarios": [scenario_z, scenario_a]})

    scenarios = load_sqs_golden_dataset(path)
    assert [s.id for s in scenarios] == ["zzz_last", "aaa_first"]


def test_nonexistent_dataset_path_is_rejected(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(DatasetError):
        load_sqs_golden_dataset(missing)

"""Deterministic tests for the Layer 2 sanitized diagnostic artifact
(Batch 23, Task 11 remediation). No network, no provider, no real_llm.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from evals.observability.layer2 import (
    DEFAULT_LAYER2_DIAGNOSTIC_DIR,
    AdapterTelemetryCapture,
    build_layer2_document,
    normalize_expected_semantics,
    normalize_intent_semantics,
    write_layer2_diagnostic,
)
from evals.scenarios.architecture_intent_nl_loader import (
    ExpectedOutcome,
    Scenario,
    load_architecture_intent_nl_golden_dataset,
    read_dataset_version,
)
from evals.scenarios.architecture_intent_nl_runner import (
    DEFAULT_DATASET_PATH,
    run_architecture_intent_nl_evals,
)
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.port import IntentProviderTimeoutError

RAW_REQUEST_SENTINEL = "RAW_REQUEST_SENTINEL_DO_NOT_PERSIST"
ASSUMPTION_SENTINEL = "ASSUMPTION_SENTINEL_DO_NOT_PERSIST"
QUESTION_SENTINEL = "QUESTION_SENTINEL_DO_NOT_PERSIST"
NAME_HINT_SENTINEL = "HINT_NAME_SENTINEL_DO_NOT_PERSIST"
API_KEY_SENTINEL = "sk-secret-key-sentinel-do-not-persist"


def _intent(**kwargs) -> ArchitectureIntent:
    defaults = dict(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
        logical_name_hint=NAME_HINT_SENTINEL,
        assumptions=(ASSUMPTION_SENTINEL,),
        unresolved_questions=(QUESTION_SENTINEL,),
    )
    defaults.update(kwargs)
    return ArchitectureIntent(**defaults)


def _scenario() -> Scenario:
    return Scenario(
        id="case1_sync_api_en",
        description="Clear synchronous API request, English.",
        natural_language_request=RAW_REQUEST_SENTINEL,
        expected=ExpectedOutcome(
            schema_valid=True,
            workload_type="api",
            interaction_pattern="synchronous",
            capabilities=("http_endpoint",),
            unresolved_questions_expected=False,
        ),
    )


class FakeIntentInterpreter:
    def __init__(self, *, results=None):
        self._results = list(results or [])
        self.calls = 0

    def interpret(self, *, natural_language_request: str, request_id: str):
        self.calls += 1
        if not self._results:
            raise AssertionError("FakeIntentInterpreter called with no canned results left")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _tiny_dataset(path: Path, *, request: str = RAW_REQUEST_SENTINEL) -> Path:
    payload = {
        "version": 1,
        "scenarios": [
            {
                "id": "case1_style_clear_api",
                "description": "case1-style clear API",
                "natural_language_request": request,
                "expected": {
                    "schema_valid": True,
                    "workload_type": "api",
                    "interaction_pattern": "synchronous",
                    "capabilities": ["http_endpoint"],
                    "unresolved_questions_expected": False,
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_normalize_intent_semantics_omits_advisory_text():
    normalized = normalize_intent_semantics(_intent())
    assert normalized == {
        "workload_type": "api",
        "interaction_pattern": "synchronous",
        "capabilities": ["http_endpoint"],
        "user_provided_hints": [],
        "unresolved_questions_present": True,
        "unresolved_questions_count": 1,
    }
    dumped = json.dumps(normalized)
    assert NAME_HINT_SENTINEL not in dumped
    assert ASSUMPTION_SENTINEL not in dumped
    assert QUESTION_SENTINEL not in dumped


def test_normalize_expected_semantics_uses_boolean_questions_flag():
    expected = normalize_expected_semantics(_scenario().expected)
    assert expected["workload_type"] == "api"
    assert expected["interaction_pattern"] == "synchronous"
    assert expected["capabilities"] == ["http_endpoint"]
    assert expected["unresolved_questions_expected"] is False
    assert "unresolved_questions" not in expected


def test_case1_style_clear_api_does_not_require_unresolved_questions():
    expected = normalize_expected_semantics(_scenario().expected)
    actual = normalize_intent_semantics(
        _intent(assumptions=(), unresolved_questions=(), logical_name_hint=None)
    )
    assert expected["unresolved_questions_expected"] is False
    assert actual["unresolved_questions_present"] is False
    assert actual["unresolved_questions_count"] == 0


def test_build_layer2_document_allowlist_and_resolver_outcomes():
    scenario = _scenario()
    intent = _intent(assumptions=(), unresolved_questions=(), logical_name_hint=None)
    result = EvalResult(
        scenario_id=scenario.id,
        evaluator="semantic_fields",
        status=EvalStatus.PASS,
        score=1.0,
        message="all specified semantic fields matched",
    )
    document = build_layer2_document(
        traces=((scenario, intent, (result,)),),
        dataset_path="evals/datasets/architecture_intent_nl_golden.json",
        run_metadata={"provider": "openai", "model": "gpt-5-nano", "prompt_version": "2"},
    )
    assert set(document) <= {"schema_version", "run", "results", "scenarios"}
    assert document["schema_version"] == "1"
    run = document["run"]
    assert run["provider"] == "openai"
    assert run["model"] == "gpt-5-nano"
    assert run["prompt_version"] == "2"
    assert run["scenario_count"] == 1
    assert run["scenario_executions"] == 1
    assert run["interpreter_invocations"] == 1
    assert run["provider_attempts"] == 0
    assert run["aggregate_result"] == "PASS"
    assert run["evaluation_count"] == 1
    scenario_row = document["scenarios"][0]
    assert scenario_row["scenario_id"] == "case1_sync_api_en"
    assert scenario_row["scenario_result"] == "PASS"
    assert scenario_row["interpreter_invocations"] == 1
    row = document["results"][0]
    assert row["scenario_id"] == "case1_sync_api_en"
    assert row["evaluator"] == "semantic_fields"
    assert row["status"] == "pass"
    assert row["resolver_outcome_expected"] == "resolved"
    assert row["resolver_outcome_actual"] == "resolved"
    assert row["expected_normalized"]["unresolved_questions_expected"] is False
    assert row["actual_normalized"]["unresolved_questions_present"] is False
    serialized = json.dumps(document)
    assert RAW_REQUEST_SENTINEL not in serialized
    assert ASSUMPTION_SENTINEL not in serialized
    assert QUESTION_SENTINEL not in serialized
    assert NAME_HINT_SENTINEL not in serialized
    assert "request_spec" not in serialized
    assert "ApiLambdaSpec" not in serialized


def test_write_layer2_diagnostic_rejects_forbidden_keys(tmp_path):
    with pytest.raises(ValueError, match="natural_language_request"):
        write_layer2_diagnostic(
            {
                "run": {"scenario_count": 0, "evaluation_count": 0},
                "results": [{"natural_language_request": RAW_REQUEST_SENTINEL}],
            },
            path=tmp_path / "bad.json",
        )
    assert not (tmp_path / "bad.json").exists()


def test_serialized_artifact_never_contains_raw_request_sentinel(tmp_path):
    scenario = _scenario()
    intent = _intent()
    result = EvalResult(
        scenario_id=scenario.id,
        evaluator="schema_validity",
        status=EvalStatus.PASS,
        score=1.0,
        message="produced a schema-valid ArchitectureIntent as expected",
    )
    document = build_layer2_document(
        traces=((scenario, intent, (result,)),),
        dataset_path=str(tmp_path / "unused.json"),
        run_metadata={"provider": "openai", "model": "gpt-5-nano"},
        telemetry_by_request_id={
            f"layer2-{scenario.id}": {
                "prompt_version": "2",
                "attempt_count": 1,
                "outcome_category": "schema_valid",
                "input_tokens": 11,
                "output_tokens": 22,
                "api_key": API_KEY_SENTINEL,
                "natural_language_request": RAW_REQUEST_SENTINEL,
            }
        },
    )
    path = tmp_path / "layer2-diagnostic.json"
    written = write_layer2_diagnostic(document, path=path)
    serialized = written.read_text(encoding="utf-8")
    assert RAW_REQUEST_SENTINEL not in serialized
    assert ASSUMPTION_SENTINEL not in serialized
    assert QUESTION_SENTINEL not in serialized
    assert NAME_HINT_SENTINEL not in serialized
    assert API_KEY_SENTINEL not in serialized
    assert "Authorization" not in serialized
    payload = json.loads(serialized)
    row = payload["results"][0]
    assert row["attempt_count"] == 1
    assert row["token_metadata"] == {"input_tokens": 11, "output_tokens": 22}
    assert row["prompt_version"] == "2"
    assert "api_key" not in json.dumps(row)


def test_default_diagnostic_dir_is_gitignored_artifacts_tree():
    assert DEFAULT_LAYER2_DIAGNOSTIC_DIR == Path("artifacts") / "evals" / "layer2"


def test_telemetry_capture_copies_only_safe_extras():
    capture = AdapterTelemetryCapture()
    logger = logging.getLogger("iac_agent.intent.adapters")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "intent interpretation schema_valid",
            extra={
                "request_id": "layer2-case1_sync_api_en",
                "provider": "openai",
                "model": "gpt-5-nano",
                "prompt_version": "2",
                "attempt_count": 1,
                "latency_ms": 12.5,
                "outcome_category": "schema_valid",
                "input_tokens": 4,
                "output_tokens": 8,
                "natural_language_request": RAW_REQUEST_SENTINEL,
            },
        )
        rec = capture.by_request_id["layer2-case1_sync_api_en"]
        assert rec["prompt_version"] == "2"
        assert rec["input_tokens"] == 4
        assert rec["latency_ms"] == 12.5
        assert "natural_language_request" not in rec
    finally:
        logger.removeHandler(capture)


def test_runner_persists_sanitized_diagnostic_when_path_given(tmp_path):
    dataset_path = _tiny_dataset(tmp_path / "dataset.json")
    diagnostic_path = tmp_path / "evals" / "layer2" / "layer2-diagnostic.json"
    suite = run_architecture_intent_nl_evals(
        interpreter=FakeIntentInterpreter(
            results=[_intent(assumptions=(), unresolved_questions=(), logical_name_hint=None)]
        ),
        dataset_path=dataset_path,
        diagnostic_path=diagnostic_path,
        run_metadata={"provider": "openai", "model": "gpt-5-nano", "prompt_version": "2"},
    )
    assert suite.errored == 0
    serialized = diagnostic_path.read_text(encoding="utf-8")
    assert RAW_REQUEST_SENTINEL not in serialized
    payload = json.loads(serialized)
    assert payload["run"]["prompt_version"] == "2"
    assert payload["run"]["scenario_count"] == 1
    evaluators = {row["evaluator"] for row in payload["results"]}
    assert evaluators == {
        "schema_validity",
        "semantic_fields",
        "forbidden_authority_absence",
        "resolver_compatibility",
    }
    assert all(
        row["actual_normalized"]["unresolved_questions_present"] is False
        for row in payload["results"]
    )
    assert all(row["resolver_outcome_actual"] == "resolved" for row in payload["results"])


def test_questions_remain_in_sanitized_diagnostics_when_present(tmp_path):
    """C: question presence/count stay observable even though they are not
    a hard semantic_fields blocker, and the raw question text is omitted."""
    dataset_path = _tiny_dataset(tmp_path / "dataset.json")
    diagnostic_path = tmp_path / "evals" / "layer2" / "layer2-diagnostic.json"
    suite = run_architecture_intent_nl_evals(
        interpreter=FakeIntentInterpreter(
            results=[
                _intent(
                    assumptions=(),
                    unresolved_questions=(QUESTION_SENTINEL,),
                    logical_name_hint=None,
                )
            ]
        ),
        dataset_path=dataset_path,
        diagnostic_path=diagnostic_path,
        run_metadata={"provider": "openai", "model": "gpt-5-nano", "prompt_version": "3"},
    )
    assert suite.errored == 0
    semantic = next(r for r in suite.results if r.evaluator == "semantic_fields")
    assert semantic.status == EvalStatus.PASS
    serialized = diagnostic_path.read_text(encoding="utf-8")
    assert QUESTION_SENTINEL not in serialized
    payload = json.loads(serialized)
    assert all(
        row["actual_normalized"]["unresolved_questions_present"] is True
        for row in payload["results"]
    )
    assert all(
        row["actual_normalized"]["unresolved_questions_count"] == 1
        for row in payload["results"]
    )
    assert all(
        row["expected_normalized"]["unresolved_questions_expected"] is False
        for row in payload["results"]
    )
    assert all(row["resolver_outcome_actual"] == "resolved" for row in payload["results"])


def test_timeout_scenario_records_provider_attempt_and_redacts_secrets():
    scenario = _scenario()
    failed = EvalResult(
        scenario_id=scenario.id,
        evaluator="schema_validity",
        status=EvalStatus.FAIL,
        score=0.0,
        message=f"provider said {API_KEY_SENTINEL}",
    )
    document = build_layer2_document(
        traces=((scenario, IntentProviderTimeoutError("slow"), (failed,)),),
        dataset_path="evals/datasets/architecture_intent_nl_golden.json",
        telemetry_by_request_id={
            "layer2-case1_sync_api_en": {
                "attempt_count": 2,
                "latency_ms": 10.5,
                "input_tokens": 3,
                "output_tokens": 4,
            }
        },
    )
    row = document["scenarios"][0]
    assert row["scenario_result"] == "PROVIDER_ERROR"
    assert row["provider_error_class"] == "timeout"
    assert row["actual"] is None
    assert row["provider_attempt_count"] == 2
    assert row["latency_ms"] == 10.5
    assert row["token_usage"] == {"input_tokens": 3, "output_tokens": 4}
    assert document["run"]["provider_attempts"] == 2
    assert document["run"]["interpreter_invocations"] == 1
    serialized = json.dumps(document)
    assert API_KEY_SENTINEL not in serialized
    assert RAW_REQUEST_SENTINEL not in serialized


def test_read_dataset_version_of_the_golden_file():
    assert read_dataset_version(DEFAULT_DATASET_PATH) == 1


def _intent_from_expected(expected: ExpectedOutcome) -> ArchitectureIntent:
    capabilities = () if expected.capabilities is None else expected.capabilities
    hints = () if expected.user_provided_hints is None else expected.user_provided_hints
    pattern = expected.interaction_pattern or "unspecified"
    workload = expected.workload_type or "unspecified"
    return ArchitectureIntent(
        workload_type=WorkloadType(workload),
        interaction_pattern=InteractionPattern(pattern),
        capabilities=frozenset(Capability(item) for item in capabilities),
        user_provided_hints=frozenset(AwsServiceHint(item) for item in hints),
    )


def test_runner_records_measured_adapter_attempts_without_leaving_info_enabled(tmp_path):
    """The live adapter logs attempt_count at INFO on the child logger.

    The test starts from the process default that suppresses INFO. It
    does not enable INFO itself and does not inject telemetry.
    """
    child = logging.getLogger("iac_agent.intent.adapters.openai")
    parent = logging.getLogger("iac_agent.intent.adapters")
    saved_child_level = child.level
    saved_parent_level = parent.level
    child.setLevel(logging.NOTSET)
    parent.setLevel(logging.NOTSET)
    assert child.isEnabledFor(logging.INFO) is False
    measured_attempts = 2

    class _LoggingInterpreter:
        def interpret(self, *, natural_language_request: str, request_id: str):
            logging.getLogger("iac_agent.intent.adapters.openai").info(
                "intent interpretation schema_valid",
                extra={
                    "request_id": request_id,
                    "attempt_count": measured_attempts,
                    "provider": "openai",
                    "model": "gpt-5-nano",
                    "prompt_version": "6",
                    "latency_ms": 1.0,
                    "outcome_category": "schema_valid",
                },
            )
            return _intent(assumptions=(), unresolved_questions=(), logical_name_hint=None)

    dataset_path = _tiny_dataset(tmp_path / "dataset.json")
    diagnostic_path = tmp_path / "layer2-diagnostic.json"
    try:
        run_architecture_intent_nl_evals(
            interpreter=_LoggingInterpreter(),
            dataset_path=dataset_path,
            diagnostic_path=diagnostic_path,
        )
        payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        assert payload["scenarios"][0]["provider_attempt_count"] == measured_attempts
        assert payload["run"]["provider_attempts"] == measured_attempts
        assert parent.level == logging.NOTSET
        assert child.isEnabledFor(logging.INFO) is False
    finally:
        child.setLevel(saved_child_level)
        parent.setLevel(saved_parent_level)


def test_golden_dataset_fake_run_records_twenty_six_executions_and_invocations(tmp_path):
    scenarios = load_architecture_intent_nl_golden_dataset(DEFAULT_DATASET_PATH)
    interpreter = FakeIntentInterpreter(
        results=[_intent_from_expected(scenario.expected) for scenario in scenarios]
    )
    diagnostic_path = tmp_path / "layer2-diagnostic.json"
    suite = run_architecture_intent_nl_evals(
        interpreter=interpreter,
        diagnostic_path=diagnostic_path,
    )
    assert suite.failed == 0
    assert interpreter.calls == 26
    payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert payload["run"]["scenario_executions"] == 26
    assert payload["run"]["interpreter_invocations"] == 26
    assert payload["run"]["provider_attempts"] == 0
    assert payload["run"]["dataset_version"] == 1
    assert payload["run"]["aggregate_result"] == "PASS"
    assert len(payload["scenarios"]) == 26

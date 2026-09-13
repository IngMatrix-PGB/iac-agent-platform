"""Unit tests for the eval domain models (EvalResult / EvalSuiteResult)."""

from __future__ import annotations

import dataclasses

import pytest

from iac_agent.domain.evals import EvalResult, EvalStatus, EvalSuiteResult


def _result(scenario_id="s1", evaluator="contract_validity", status=EvalStatus.PASS, score=1.0):
    return EvalResult(
        scenario_id=scenario_id, evaluator=evaluator, status=status, score=score, message="m"
    )


def test_eval_result_is_immutable():
    result = _result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = EvalStatus.FAIL  # type: ignore[misc]


def test_suite_derived_counts():
    suite = EvalSuiteResult(
        results=(
            _result(status=EvalStatus.PASS),
            _result(status=EvalStatus.PASS),
            _result(status=EvalStatus.FAIL),
            _result(status=EvalStatus.ERROR),
        )
    )
    assert suite.total == 4
    assert suite.passed == 2
    assert suite.failed == 1
    assert suite.errored == 1


def test_suite_pass_rate():
    suite = EvalSuiteResult(
        results=(_result(status=EvalStatus.PASS), _result(status=EvalStatus.FAIL))
    )
    assert suite.pass_rate == 50.0


def test_pass_rate_is_zero_for_empty_suite():
    assert EvalSuiteResult(results=()).pass_rate == 0.0


def test_pass_score_is_one():
    result = _result(status=EvalStatus.PASS, score=1.0)
    assert result.score == 1.0


def test_fail_score_is_zero():
    result = _result(status=EvalStatus.FAIL, score=0.0)
    assert result.score == 0.0


def test_error_is_distinguishable_from_fail():
    error_result = _result(status=EvalStatus.ERROR, score=0.0)
    fail_result = _result(status=EvalStatus.FAIL, score=0.0)
    assert error_result.status is not fail_result.status
    assert error_result.status is EvalStatus.ERROR

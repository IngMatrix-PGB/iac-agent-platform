"""Unit tests for the deterministic SQS scenario evaluators.

No Terraform, Checkov, AWS, network, or LLM dependency — these
evaluators use only the Pydantic contract, the pure renderer, and typed
PlanSummary/CheckovScanResult fixtures.
"""

from __future__ import annotations

from evals.evaluators.sqs import (
    evaluate_contract_validity,
    evaluate_field_expectations,
    evaluate_rendering_determinism,
    evaluate_security_status,
)
from evals.scenarios.loader import ExpectedOutcome, Scenario
from iac_agent.domain.evals import EvalStatus


def _scenario(scenario_id, input_data, expected: ExpectedOutcome) -> Scenario:
    return Scenario(id=scenario_id, description="d", input=input_data, expected=expected)


def _valid_expected(**overrides):
    defaults = dict(
        valid=True,
        queue_name="order-events",
        fifo=False,
        dlq_enabled=True,
        encryption_enabled=True,
        kms_key_id=None,
        overall_security_status="pass",
    )
    defaults.update(overrides)
    return ExpectedOutcome(**defaults)


# ---------------------------------------------------------------------------
# contract_validity
# ---------------------------------------------------------------------------


def test_valid_scenario_passes_validity_eval():
    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    result, spec = evaluate_contract_validity(scenario)

    assert result.status is EvalStatus.PASS
    assert result.score == 1.0
    assert spec is not None


def test_expected_invalid_scenario_passes_when_pydantic_rejects_it():
    scenario = _scenario("s", {"name": "orders", "fifo": True}, ExpectedOutcome(valid=False))
    result, spec = evaluate_contract_validity(scenario)

    assert result.status is EvalStatus.PASS
    assert spec is None


def test_unexpected_valid_invalid_mismatch_fails():
    # Expected invalid, but this input actually constructs successfully.
    scenario = _scenario("s", {"name": "order-events"}, ExpectedOutcome(valid=False))
    result, spec = evaluate_contract_validity(scenario)

    assert result.status is EvalStatus.FAIL
    assert result.score == 0.0
    assert spec is None


def test_unexpected_invalid_when_valid_was_expected_fails():
    scenario = _scenario("s", {"name": "orders", "fifo": True}, _valid_expected())
    result, spec = evaluate_contract_validity(scenario)

    assert result.status is EvalStatus.FAIL
    assert spec is None


def test_unrelated_internal_exception_becomes_error_not_pass(monkeypatch):
    import evals.evaluators.sqs as sqs_evaluators_module

    def _boom(**kwargs):
        raise RuntimeError("simulated unrelated internal failure")

    monkeypatch.setattr(sqs_evaluators_module, "SQSResourceSpec", _boom)

    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    result, spec = evaluate_contract_validity(scenario)

    assert result.status is EvalStatus.ERROR
    assert spec is None


# ---------------------------------------------------------------------------
# field_expectations
# ---------------------------------------------------------------------------


def test_expected_fields_match():
    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_field_expectations(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_field_regression_is_detected():
    # A "regression" fixture: the scenario's expectation says fifo=True
    # but the constructed spec (from a plain non-FIFO input) is fifo=False.
    scenario = _scenario(
        "s",
        {"name": "order-events"},
        _valid_expected(fifo=True, queue_name="order-events"),
    )
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_field_expectations(scenario, spec)
    assert result.status is EvalStatus.FAIL
    assert result.score == 0.0
    assert "fifo" in result.message


def test_optional_kms_key_id_behavior():
    scenario = _scenario(
        "s",
        {"name": "order-events", "encryption": {"kms_key_id": "alias/aws/sqs"}},
        _valid_expected(kms_key_id="alias/aws/sqs"),
    )
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_field_expectations(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_dlq_expectation():
    scenario = _scenario(
        "s",
        {"name": "order-events", "dlq": {"enabled": False, "max_receive_count": None}},
        _valid_expected(dlq_enabled=False, overall_security_status="warn"),
    )
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_field_expectations(scenario, spec)
    assert result.status is EvalStatus.PASS


# ---------------------------------------------------------------------------
# rendering_determinism
# ---------------------------------------------------------------------------


def test_repeated_render_is_byte_identical():
    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_rendering_determinism(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_equivalent_tag_order_is_byte_identical():
    from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
    from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

    spec_a = SQSResourceSpec(name="order-events", tags={"A": "1", "B": "2"})
    spec_b = SQSResourceSpec(name="order-events", tags={"B": "2", "A": "1"})

    renderer = TerraformCompositionRenderer()
    assert renderer.render(spec_a).files == renderer.render(spec_b).files


def test_invalid_scenario_is_never_rendered():
    """The runner never calls the rendering evaluator for an
    expected-invalid scenario at all — proven at the runner level in
    test_runner.py. Here we confirm the evaluator has no spec to work
    with in that case (spec is None), which is what makes that
    skip-by-construction possible."""
    scenario = _scenario("s", {"name": "orders", "fifo": True}, ExpectedOutcome(valid=False))
    _, spec = evaluate_contract_validity(scenario)
    assert spec is None


# ---------------------------------------------------------------------------
# security_status
# ---------------------------------------------------------------------------


def test_secure_scenario_gives_pass():
    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_security_status(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_dlq_disabled_scenario_matches_expected_warn():
    scenario = _scenario(
        "s",
        {"name": "order-events", "dlq": {"enabled": False, "max_receive_count": None}},
        _valid_expected(dlq_enabled=False, overall_security_status="warn"),
    )
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_security_status(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_block_mismatch_is_detected():
    # Expectation says "block" but the real gate produces "pass" for a
    # perfectly secure spec — this must FAIL, not silently pass.
    scenario = _scenario(
        "s", {"name": "order-events"}, _valid_expected(overall_security_status="block")
    )
    _, spec = evaluate_contract_validity(scenario)

    result = evaluate_security_status(scenario, spec)
    assert result.status is EvalStatus.FAIL
    assert "block" in result.message


def test_clean_scanner_fixture_adds_no_fake_checkov_pass_finding():
    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    _, spec = evaluate_contract_validity(scenario)

    from evals.evaluators.sqs import _CLEAN_CHECKOV_RESULT

    assert _CLEAN_CHECKOV_RESULT.findings == ()
    result = evaluate_security_status(scenario, spec)
    assert result.status is EvalStatus.PASS


def test_security_evaluator_uses_security_gate_not_duplicated_precedence(monkeypatch):
    """If evaluate_security_status ever stops calling evaluate_security_gate
    directly, this test (via monkeypatching the gate call) would catch the
    drift by observing the mock was never invoked."""
    import evals.evaluators.sqs as sqs_evaluators_module

    called = {"count": 0}
    original = sqs_evaluators_module.evaluate_security_gate

    def _spy(*args, **kwargs):
        called["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(sqs_evaluators_module, "evaluate_security_gate", _spy)

    scenario = _scenario("s", {"name": "order-events"}, _valid_expected())
    _, spec = evaluate_contract_validity(scenario)
    evaluate_security_status(scenario, spec)

    assert called["count"] == 1

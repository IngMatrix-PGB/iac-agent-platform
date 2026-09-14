"""Unit tests for the Lambda resource contract (Phase 2, Batch 18).

Covers LambdaResourceSpec: valid construction, every required
hard-failure rule, boundary values, and canonical serialization. No
network, filesystem, LLM, or Terraform dependency is exercised
anywhere in this module.
"""

import json

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.lambda_function.contract import (
    LambdaArchitecture,
    LambdaResourceSpec,
    LambdaRuntime,
    LambdaTracingMode,
)


def _spec(**overrides) -> LambdaResourceSpec:
    defaults = {"name": "orders-processor", "handler": "app.handler"}
    defaults.update(overrides)
    return LambdaResourceSpec(**defaults)


# ---------------------------------------------------------------------------
# Valid cases / defaults
# ---------------------------------------------------------------------------


def test_function_with_all_defaults():
    spec = _spec()

    assert spec.resource_type == "lambda_function"
    assert spec.name == "orders-processor"
    assert spec.environment is None
    assert spec.runtime is LambdaRuntime.PYTHON3_12
    assert spec.handler == "app.handler"
    assert spec.architecture is LambdaArchitecture.ARM64
    assert spec.memory_size_mb == 256
    assert spec.timeout_seconds == 30
    assert spec.reserved_concurrency is None
    assert spec.tracing_mode is LambdaTracingMode.ACTIVE
    assert spec.log_retention_days == 365
    assert spec.environment_variables == {}
    assert spec.tags == {}


def test_function_with_environment_set():
    spec = _spec(environment="staging")
    assert spec.environment == "staging"


def test_function_with_custom_tags():
    spec = _spec(tags={"Service": "orders", "Team": "data"})
    assert spec.tags == {"Service": "orders", "Team": "data"}


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("architecture", [LambdaArchitecture.X86_64, LambdaArchitecture.ARM64])
def test_architecture_accepts_every_valid_value(architecture):
    spec = _spec(architecture=architecture)
    assert spec.architecture is architecture


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_memory_at_minimum_is_valid():
    spec = _spec(memory_size_mb=128)
    assert spec.memory_size_mb == 128


def test_memory_at_maximum_is_valid():
    spec = _spec(memory_size_mb=10240)
    assert spec.memory_size_mb == 10240


def test_memory_below_minimum_is_rejected():
    with pytest.raises(ValidationError, match="between 128 and 10240"):
        _spec(memory_size_mb=127)


def test_memory_above_maximum_is_rejected():
    with pytest.raises(ValidationError, match="between 128 and 10240"):
        _spec(memory_size_mb=10241)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_timeout_at_minimum_is_valid():
    spec = _spec(timeout_seconds=1)
    assert spec.timeout_seconds == 1


def test_timeout_at_maximum_is_valid():
    spec = _spec(timeout_seconds=900)
    assert spec.timeout_seconds == 900


def test_timeout_below_minimum_is_rejected():
    with pytest.raises(ValidationError, match="between 1 and 900"):
        _spec(timeout_seconds=0)


def test_timeout_above_maximum_is_rejected():
    with pytest.raises(ValidationError, match="between 1 and 900"):
        _spec(timeout_seconds=901)


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


def test_tracing_active():
    spec = _spec(tracing_mode=LambdaTracingMode.ACTIVE)
    assert spec.tracing_mode is LambdaTracingMode.ACTIVE


def test_tracing_pass_through():
    spec = _spec(tracing_mode=LambdaTracingMode.PASS_THROUGH)
    assert spec.tracing_mode is LambdaTracingMode.PASS_THROUGH


# ---------------------------------------------------------------------------
# Reserved concurrency
# ---------------------------------------------------------------------------


def test_reserved_concurrency_set():
    spec = _spec(reserved_concurrency=5)
    assert spec.reserved_concurrency == 5


def test_reserved_concurrency_zero_is_valid():
    """0 is a legitimate value (fully throttles the function) — never
    confused with "unset"."""
    spec = _spec(reserved_concurrency=0)
    assert spec.reserved_concurrency == 0


def test_reserved_concurrency_omitted_defaults_to_none():
    spec = _spec()
    assert spec.reserved_concurrency is None


def test_reserved_concurrency_negative_is_rejected():
    with pytest.raises(ValidationError, match=">= 0"):
        _spec(reserved_concurrency=-1)


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------


def test_valid_environment_variables():
    spec = _spec(environment_variables={"LOG_LEVEL": "INFO", "SERVICE_NAME": "orders"})
    assert spec.environment_variables == {"LOG_LEVEL": "INFO", "SERVICE_NAME": "orders"}


def test_environment_variable_name_starting_with_digit_is_rejected():
    with pytest.raises(ValidationError, match="must start with a letter"):
        _spec(environment_variables={"1LOG": "INFO"})


def test_environment_variable_name_too_short_is_rejected():
    with pytest.raises(ValidationError, match="at least 2 characters"):
        _spec(environment_variables={"A": "INFO"})


def test_environment_variable_name_with_invalid_character_is_rejected():
    with pytest.raises(ValidationError, match="letters, digits, and underscores"):
        _spec(environment_variables={"LOG-LEVEL": "INFO"})


@pytest.mark.parametrize(
    "reserved_name", ["AWS_REGION", "AWS_LAMBDA_FUNCTION_NAME", "LAMBDA_TASK_ROOT"]
)
def test_reserved_environment_variable_names_are_rejected(reserved_name):
    with pytest.raises(ValidationError, match="reserved by the Lambda runtime"):
        _spec(environment_variables={reserved_name: "value"})


def test_underscore_prefixed_reserved_names_are_rejected_too():
    """`_HANDLER`/`_X_AMZN_TRACE_ID` are reserved by the Lambda runtime
    but don't even match AWS's own public env-var naming convention
    (start with a letter) — still correctly rejected, just by the
    general name-pattern rule rather than the reserved-name check."""
    with pytest.raises(ValidationError):
        _spec(environment_variables={"_HANDLER": "value"})


def test_environment_variables_exceeding_aggregate_limit_are_rejected():
    huge_value = "x" * 4096
    with pytest.raises(ValidationError, match="aggregate limit"):
        _spec(environment_variables={"BIG_VALUE": huge_value})


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def test_handler_with_namespaced_form_is_valid():
    spec = _spec(handler="package.module.handler")
    assert spec.handler == "package.module.handler"


def test_empty_handler_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="")


def test_handler_without_dot_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="handler")


def test_handler_with_whitespace_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="app handler")


def test_handler_with_path_traversal_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="../../etc.passwd")


def test_handler_with_path_separator_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="app/handler")


def test_handler_with_shell_syntax_is_rejected():
    with pytest.raises(ValidationError, match="module.function"):
        _spec(handler="app.handler; rm -rf /")


# ---------------------------------------------------------------------------
# Function name
# ---------------------------------------------------------------------------


def test_name_at_minimum_length_is_valid():
    spec = _spec(name="a")
    assert spec.name == "a"


def test_name_at_maximum_length_is_valid():
    name = "a" * 64
    spec = _spec(name=name)
    assert spec.name == name


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError, match="between 1 and 64"):
        _spec(name="a" * 65)


def test_name_with_unsupported_character_is_rejected():
    with pytest.raises(ValidationError, match="letters, digits, underscores, and hyphens"):
        _spec(name="orders.processor")


# ---------------------------------------------------------------------------
# Log retention
# ---------------------------------------------------------------------------


def test_log_retention_default_is_one_year():
    spec = _spec()
    assert spec.log_retention_days == 365


@pytest.mark.parametrize("days", [1, 30, 90, 365, 3653])
def test_log_retention_accepts_every_documented_value_sampled(days):
    spec = _spec(log_retention_days=days)
    assert spec.log_retention_days == days


def test_log_retention_rejects_unsupported_value():
    with pytest.raises(ValidationError, match="must be one of"):
        _spec(log_retention_days=45)


def test_log_retention_rejects_zero():
    with pytest.raises(ValidationError, match="must be one of"):
        _spec(log_retention_days=0)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialization_is_fully_json_serializable():
    spec = _spec()
    dumped = spec.model_dump(mode="json")
    json.dumps(dumped)


def test_serialization_round_trip_reconstructs_an_equal_spec():
    original = _spec(
        environment="staging",
        architecture=LambdaArchitecture.X86_64,
        memory_size_mb=512,
        timeout_seconds=60,
        reserved_concurrency=10,
        tracing_mode=LambdaTracingMode.PASS_THROUGH,
        log_retention_days=90,
        environment_variables={"LOG_LEVEL": "DEBUG"},
        tags={"Service": "orders"},
    )
    dumped = original.model_dump(mode="json")
    reconstructed = LambdaResourceSpec(**dumped)

    assert reconstructed == original
    assert reconstructed.model_dump(mode="json") == dumped

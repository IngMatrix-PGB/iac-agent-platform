"""Unit tests for the API Gateway (HTTP API) resource contract (Phase
2, Batch 20).

Covers `ApiGatewayResourceSpec`: valid construction, every required
hard-failure rule, boundary values, and determinism. No network,
filesystem, LLM, or Terraform dependency is exercised anywhere in this
module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec


def _spec(**overrides) -> ApiGatewayResourceSpec:
    defaults = {"name": "orders-api"}
    defaults.update(overrides)
    return ApiGatewayResourceSpec(**defaults)


def test_api_with_all_defaults():
    spec = _spec()
    assert spec.resource_type == "api_gateway"
    assert spec.name == "orders-api"
    assert spec.description is None
    assert spec.environment is None
    assert spec.tags == {}


def test_api_with_description():
    spec = _spec(description="Orders API")
    assert spec.description == "Orders API"


def test_api_with_environment_set():
    spec = _spec(environment="staging")
    assert spec.environment == "staging"


def test_api_with_custom_tags():
    spec = _spec(tags={"Service": "orders"})
    assert spec.tags == {"Service": "orders"}


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="")


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="a" * 129)


def test_name_at_max_length_is_accepted():
    spec = _spec(name="a" * 128)
    assert len(spec.name) == 128


def test_name_with_invalid_character_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="orders api")


def test_description_too_long_is_rejected():
    with pytest.raises(ValidationError):
        _spec(description="a" * 257)


def test_description_at_max_length_is_accepted():
    spec = _spec(description="a" * 256)
    assert len(spec.description) == 256


def test_protocol_type_is_not_a_configurable_field():
    """There is no field a caller could set to request a WEBSOCKET
    protocol — the trusted module hardcodes HTTP unconditionally."""
    assert "protocol_type" not in ApiGatewayResourceSpec.model_fields


def test_constructing_the_same_input_twice_is_deterministic():
    assert _spec() == _spec()

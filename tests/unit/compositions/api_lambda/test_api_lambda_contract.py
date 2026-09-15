"""Unit tests for the API-Gateway-to-Lambda composition contract
(Phase 2, Batch 20).

Covers `RouteSpec`/`HttpMethod` and `ApiLambdaSpec`: valid
construction/defaults, every cross-resource invariant, and route-path
validation boundaries. No network, filesystem, LLM, or Terraform
dependency is exercised anywhere in this module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec


def _spec(**overrides) -> ApiLambdaSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
    }
    defaults.update(overrides)
    return ApiLambdaSpec(**defaults)


# ---------------------------------------------------------------------------
# RouteSpec / HttpMethod
# ---------------------------------------------------------------------------


def test_route_key_combines_method_and_path():
    route = RouteSpec(method=HttpMethod.POST, path="/orders")
    assert route.route_key == "POST /orders"


def test_route_key_for_root_path():
    route = RouteSpec(method=HttpMethod.GET, path="/")
    assert route.route_key == "GET /"


def test_route_with_path_parameter():
    route = RouteSpec(method=HttpMethod.GET, path="/orders/{id}")
    assert route.route_key == "GET /orders/{id}"


@pytest.mark.parametrize("method", list(HttpMethod))
def test_every_supported_method_constructs(method):
    route = RouteSpec(method=method, path="/orders")
    assert route.method is method


def test_http_method_has_exactly_five_members():
    assert {m.value for m in HttpMethod} == {"GET", "POST", "PUT", "PATCH", "DELETE"}


def test_any_method_is_not_supported():
    with pytest.raises(ValueError):
        HttpMethod("ANY")


def test_empty_path_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="")


def test_path_missing_leading_slash_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="orders")


def test_whitespace_only_path_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="   ")


def test_path_with_internal_whitespace_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/orders /list")


def test_path_with_control_character_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/orders\n")


def test_path_with_trailing_slash_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/orders/")


def test_root_path_is_the_one_exception_to_trailing_slash_rule():
    route = RouteSpec(method=HttpMethod.GET, path="/")
    assert route.path == "/"


def test_path_with_empty_segment_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/orders//list")


def test_path_too_long_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/" + "a" * 512)


def test_malformed_path_parameter_is_rejected():
    with pytest.raises(ValidationError):
        RouteSpec(method=HttpMethod.GET, path="/orders/{}")


def test_deterministic_rendering_of_the_same_route_input():
    assert RouteSpec(method=HttpMethod.GET, path="/orders") == RouteSpec(
        method=HttpMethod.GET, path="/orders"
    )


# ---------------------------------------------------------------------------
# ApiLambdaSpec: valid cases / defaults
# ---------------------------------------------------------------------------


def test_composition_with_all_defaults():
    spec = _spec()
    assert spec.composition_type == "api_gateway_lambda"
    assert spec.name == "orders-api-worker"
    assert spec.environment is None
    assert isinstance(spec.api, ApiGatewayResourceSpec)
    assert isinstance(spec.function, LambdaResourceSpec)
    assert spec.route.route_key == "POST /orders"
    assert spec.tags == {}


def test_sub_specs_are_reused_verbatim_not_duplicated():
    api = ApiGatewayResourceSpec(name="orders-api", description="Orders API")
    function = LambdaResourceSpec(name="orders-handler", handler="app.handler", memory_size_mb=512)
    spec = _spec(api=api, function=function)
    assert spec.api.description == "Orders API"
    assert spec.function.memory_size_mb == 512


def test_composition_with_custom_tags():
    spec = _spec(tags={"Owner": "platform"})
    assert spec.tags == {"Owner": "platform"}


def test_composition_with_environment_set_and_consistent_sub_specs():
    spec = _spec(
        environment="staging",
        api=ApiGatewayResourceSpec(name="orders-api", environment="staging"),
    )
    assert spec.environment == "staging"
    assert spec.api.environment == "staging"


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="")


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="a" * 65)


def test_name_with_invalid_character_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="orders api worker")


# ---------------------------------------------------------------------------
# Cross-resource type invariants
# ---------------------------------------------------------------------------


def test_api_field_rejects_a_value_the_api_contract_itself_would_reject():
    with pytest.raises(ValidationError):
        _spec(api={"name": "orders api"})


def test_function_field_requires_a_handler():
    with pytest.raises(ValidationError):
        _spec(function={"name": "orders-handler"})


# ---------------------------------------------------------------------------
# No duplicate generated logical identifiers
# ---------------------------------------------------------------------------


def test_duplicate_api_and_function_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            api=ApiGatewayResourceSpec(name="orders"),
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
        )


# ---------------------------------------------------------------------------
# Environment consistency
# ---------------------------------------------------------------------------


def test_environment_mismatch_with_api_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            api=ApiGatewayResourceSpec(name="orders-api", environment="production"),
        )


def test_environment_mismatch_with_function_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            function=LambdaResourceSpec(
                name="orders-handler", handler="app.handler", environment="production"
            ),
        )


def test_sub_spec_environment_is_ignored_when_composition_environment_is_unset():
    spec = _spec(api=ApiGatewayResourceSpec(name="orders-api", environment="production"))
    assert spec.environment is None
    assert spec.api.environment == "production"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_constructing_the_same_input_twice_is_deterministic():
    assert _spec() == _spec()

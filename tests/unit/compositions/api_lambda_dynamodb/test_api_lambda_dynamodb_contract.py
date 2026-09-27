"""Unit tests for the API-Gateway-to-Lambda-to-DynamoDB composition
contract (Batch 26).

`ApiLambdaDynamoDbSpec` is composition #3. `RouteSpec`/`HttpMethod` are
reused verbatim from `iac_agent.compositions.api_lambda.contract` —
this file proves that reuse is real (import identity), not a
duplicate. No network, filesystem, LLM, or Terraform dependency is
exercised anywhere in this module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import iac_agent.compositions.api_lambda.contract as api_lambda_contract
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import (
    ApiLambdaDynamoDbSpec,
    HttpMethod as ReexportedHttpMethod,
    RouteSpec as ReexportedRouteSpec,
)
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec


def _spec(**overrides) -> ApiLambdaDynamoDbSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
        "table": DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
        ),
    }
    defaults.update(overrides)
    return ApiLambdaDynamoDbSpec(**defaults)


# ---------------------------------------------------------------------------
# Reuse, not duplication
# ---------------------------------------------------------------------------


def test_route_spec_is_reused_verbatim_from_api_lambda():
    assert ReexportedRouteSpec is api_lambda_contract.RouteSpec


def test_http_method_is_reused_verbatim_from_api_lambda():
    assert ReexportedHttpMethod is api_lambda_contract.HttpMethod


# ---------------------------------------------------------------------------
# Structural distinctness from ApiLambdaSpec (the core dispatch-safety invariant)
# ---------------------------------------------------------------------------


def test_api_lambda_dynamodb_spec_is_not_a_subclass_of_api_lambda_spec():
    assert not issubclass(ApiLambdaDynamoDbSpec, ApiLambdaSpec)


def test_api_lambda_dynamodb_spec_instance_is_not_an_api_lambda_spec_instance():
    assert not isinstance(_spec(), ApiLambdaSpec)


# ---------------------------------------------------------------------------
# Valid cases / defaults
# ---------------------------------------------------------------------------


def test_composition_with_all_defaults():
    spec = _spec()
    assert spec.composition_type == "api_gateway_lambda_dynamodb"
    assert spec.name == "orders-api-worker"
    assert spec.environment is None
    assert isinstance(spec.api, ApiGatewayResourceSpec)
    assert isinstance(spec.function, LambdaResourceSpec)
    assert isinstance(spec.table, DynamoDBResourceSpec)
    assert spec.route.route_key == "POST /orders"
    assert spec.tags == {}


def test_sub_specs_are_reused_verbatim_not_duplicated():
    table = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
        point_in_time_recovery=False,
    )
    spec = _spec(table=table)
    assert spec.table.point_in_time_recovery is False


def test_composition_with_custom_tags():
    spec = _spec(tags={"Owner": "platform"})
    assert spec.tags == {"Owner": "platform"}


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


def test_table_field_requires_a_partition_key():
    with pytest.raises(ValidationError):
        _spec(table={"name": "orders-table"})


# ---------------------------------------------------------------------------
# No duplicate generated logical identifiers (3-way, extending ApiLambdaSpec's
# 2-way check the same way ServerlessWorkerSpec extends it to 3 names)
# ---------------------------------------------------------------------------


def test_duplicate_api_and_function_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            api=ApiGatewayResourceSpec(name="orders"),
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
        )


def test_duplicate_api_and_table_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            api=ApiGatewayResourceSpec(name="orders"),
            table=DynamoDBResourceSpec(
                name="orders", partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING)
            ),
        )


def test_duplicate_function_and_table_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
            table=DynamoDBResourceSpec(
                name="orders", partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING)
            ),
        )


# ---------------------------------------------------------------------------
# Environment consistency (3-way)
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


def test_environment_mismatch_with_table_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            table=DynamoDBResourceSpec(
                name="orders-table",
                partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
                environment="production",
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

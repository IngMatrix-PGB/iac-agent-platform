"""Unit tests for the API-Gateway-to-Lambda-to-DynamoDB Terraform
composition renderer (Batch 26).

Covers `ApiLambdaDynamoDbTerraformRenderer`'s string output directly.
Real `terraform fmt`/`init`/`validate`/`plan` proof lives in
`tests/integration/test_api_lambda_dynamodb_renderer_terraform.py`
(Gate B, not this file) — this suite never shells out to any binary.
"""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.api_lambda_dynamodb.renderer import (
    ApiLambdaDynamoDbModuleSources,
    ApiLambdaDynamoDbTerraformRenderer,
)
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

_SOURCES = ApiLambdaDynamoDbModuleSources(
    api="../../terraform/modules/api_gateway",
    function="../../terraform/modules/lambda",
    table="../../terraform/modules/dynamodb",
)


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


def _render(spec: ApiLambdaDynamoDbSpec) -> str:
    composition = ApiLambdaDynamoDbTerraformRenderer().render(spec, module_sources=_SOURCES)
    return composition.files["main.tf"]


def test_output_is_exactly_main_tf_and_versions_tf():
    composition = ApiLambdaDynamoDbTerraformRenderer().render(_spec(), module_sources=_SOURCES)
    assert set(composition.files) == {"main.tf", "versions.tf"}


def test_never_emits_a_raw_single_resource_block():
    main_tf = _render(_spec())
    for forbidden in (
        'resource "aws_apigatewayv2_api"',
        'resource "aws_apigatewayv2_stage"',
        'resource "aws_lambda_function"',
        'resource "aws_iam_role"',
        'resource "aws_dynamodb_table"',
    ):
        assert forbidden not in main_tf


def test_instantiates_all_three_trusted_modules():
    main_tf = _render(_spec())
    assert 'module "api" {' in main_tf
    assert 'module "function" {' in main_tf
    assert 'module "table" {' in main_tf
    assert main_tf.count(f'source = "{_SOURCES.api}"') == 1
    assert main_tf.count(f'source = "{_SOURCES.function}"') == 1
    assert main_tf.count(f'source = "{_SOURCES.table}"') == 1


# ---------------------------------------------------------------------------
# API Gateway integration / route / Lambda permission — reused technique
# from api_lambda's own renderer
# ---------------------------------------------------------------------------


def test_integration_is_aws_proxy_with_payload_format_2():
    main_tf = _render(_spec())
    assert 'resource "aws_apigatewayv2_integration" "lambda" {' in main_tf
    assert 'integration_type       = "AWS_PROXY"' in main_tf
    assert 'payload_format_version = "2.0"' in main_tf


def test_route_key_matches_method_and_path():
    main_tf = _render(_spec(route=RouteSpec(method=HttpMethod.GET, path="/orders/{id}")))
    assert 'route_key = "GET /orders/{id}"' in main_tf


def test_never_creates_an_implicit_default_route():
    main_tf = _render(_spec())
    assert '"$default"' not in main_tf.split("aws_apigatewayv2_route")[1].split("}")[0]


def test_lambda_permission_grants_exactly_invoke_function_to_apigateway_principal():
    main_tf = _render(_spec())
    assert 'resource "aws_lambda_permission" "api_gateway" {' in main_tf
    assert 'action        = "lambda:InvokeFunction"' in main_tf
    assert 'principal     = "apigateway.amazonaws.com"' in main_tf


def test_lambda_permission_never_uses_a_wildcard_principal():
    main_tf = _render(_spec())
    assert '"*"' not in main_tf


# ---------------------------------------------------------------------------
# DynamoDB table + write-scope IAM — reused technique from
# serverless_worker's own renderer, action set restricted per the
# closed Batch 26 decision
# ---------------------------------------------------------------------------


def test_table_module_reflects_the_spec():
    main_tf = _render(
        _spec(
            table=DynamoDBResourceSpec(
                name="custom-table",
                partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
            )
        )
    )
    assert '"custom-table"' in main_tf
    assert '"pk"' in main_tf


def test_exactly_one_dynamodb_iam_role_policy_block():
    main_tf = _render(_spec())
    assert main_tf.count('resource "aws_iam_role_policy"') == 1


def test_dynamodb_write_policy_grants_exactly_put_item():
    main_tf = _render(_spec())
    policy_block = main_tf.split('data "aws_iam_policy_document" "dynamodb_write"')[1].split(
        'resource "aws_iam_role_policy"'
    )[0]
    assert '"dynamodb:PutItem"' in policy_block
    for forbidden_action in (
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem",
    ):
        assert forbidden_action not in policy_block
    assert "dynamodb:*" not in policy_block


def test_dynamodb_write_policy_scoped_to_the_table_arn_only():
    main_tf = _render(_spec())
    policy_block = main_tf.split('data "aws_iam_policy_document" "dynamodb_write"')[1].split(
        'resource "aws_iam_role_policy"'
    )[0]
    assert "resources = [module.table.table_arn]" in policy_block


def test_dynamodb_write_policy_attaches_to_the_function_execution_role():
    main_tf = _render(_spec())
    assert "role   = module.function.execution_role_name" in main_tf


def test_dynamodb_write_policy_never_uses_a_wildcard_resource():
    main_tf = _render(_spec())
    policy_block = main_tf.split('data "aws_iam_policy_document" "dynamodb_write"')[1].split(
        'resource "aws_iam_role_policy"'
    )[0]
    assert '"*"' not in policy_block


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_the_same_spec_twice_is_byte_identical():
    spec = _spec()
    first = ApiLambdaDynamoDbTerraformRenderer().render(spec, module_sources=_SOURCES)
    second = ApiLambdaDynamoDbTerraformRenderer().render(spec, module_sources=_SOURCES)
    assert first.files == second.files

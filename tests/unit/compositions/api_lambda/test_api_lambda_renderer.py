"""Unit tests for the API-Gateway-to-Lambda Terraform composition
renderer (Phase 2, Batch 20).

Covers `ApiLambdaTerraformRenderer`'s string output directly —
structural content (module blocks, the integration, the route, the
Lambda permission) and determinism. Real `terraform fmt`/`init`/
`validate`/`plan` proof lives in
`tests/integration/test_api_lambda_renderer_terraform.py`, not here —
this suite never shells out to any binary.
"""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda.renderer import (
    ApiLambdaModuleSources,
    ApiLambdaTerraformRenderer,
)
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

_SOURCES = ApiLambdaModuleSources(
    api="../../terraform/modules/api_gateway", function="../../terraform/modules/lambda"
)


def _spec(**overrides) -> ApiLambdaSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
    }
    defaults.update(overrides)
    return ApiLambdaSpec(**defaults)


def _render(spec: ApiLambdaSpec) -> str:
    composition = ApiLambdaTerraformRenderer().render(spec, module_sources=_SOURCES)
    return composition.files["main.tf"]


def test_output_is_exactly_main_tf_and_versions_tf():
    composition = ApiLambdaTerraformRenderer().render(_spec(), module_sources=_SOURCES)
    assert set(composition.files) == {"main.tf", "versions.tf"}


def test_never_emits_a_raw_single_resource_block():
    main_tf = _render(_spec())
    for forbidden in (
        'resource "aws_apigatewayv2_api"',
        'resource "aws_apigatewayv2_stage"',
        'resource "aws_lambda_function"',
        'resource "aws_iam_role"',
    ):
        assert forbidden not in main_tf


def test_instantiates_both_trusted_modules():
    main_tf = _render(_spec())
    assert 'module "api" {' in main_tf
    assert 'module "function" {' in main_tf
    assert main_tf.count(f'source = "{_SOURCES.api}"') == 1
    assert main_tf.count(f'source = "{_SOURCES.function}"') == 1


def test_function_module_reflects_the_spec():
    main_tf = _render(
        _spec(function=LambdaResourceSpec(name="custom-handler", handler="pkg.mod.handler"))
    )
    assert '"custom-handler"' in main_tf
    assert '"pkg.mod.handler"' in main_tf


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_integration_is_aws_proxy_with_payload_format_2():
    main_tf = _render(_spec())
    assert 'resource "aws_apigatewayv2_integration" "lambda" {' in main_tf
    assert 'integration_type       = "AWS_PROXY"' in main_tf
    assert 'integration_method     = "POST"' in main_tf
    assert 'payload_format_version = "2.0"' in main_tf
    assert "integration_uri        = module.function.function_arn" in main_tf


def test_integration_method_is_always_post_regardless_of_route_method():
    for method in HttpMethod:
        main_tf = _render(_spec(route=RouteSpec(method=method, path="/orders")))
        assert 'integration_method     = "POST"' in main_tf


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_route_key_matches_method_and_path():
    main_tf = _render(_spec(route=RouteSpec(method=HttpMethod.GET, path="/orders/{id}")))
    assert 'route_key = "GET /orders/{id}"' in main_tf


def test_route_targets_the_integration():
    main_tf = _render(_spec())
    assert 'target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"' in main_tf


def test_never_creates_an_implicit_default_route():
    main_tf = _render(_spec())
    assert '"$default"' not in main_tf.split("aws_apigatewayv2_route")[1].split("}")[0]


# ---------------------------------------------------------------------------
# Lambda permission
# ---------------------------------------------------------------------------


def test_lambda_permission_grants_exactly_invoke_function_to_apigateway_principal():
    main_tf = _render(_spec())
    assert 'resource "aws_lambda_permission" "api_gateway" {' in main_tf
    assert 'action        = "lambda:InvokeFunction"' in main_tf
    assert 'principal     = "apigateway.amazonaws.com"' in main_tf
    assert "function_name = module.function.function_name" in main_tf


def test_lambda_permission_never_uses_a_wildcard_principal():
    main_tf = _render(_spec())
    assert '"*"' not in main_tf


def test_lambda_permission_source_arn_references_the_api_execution_arn():
    main_tf = _render(_spec())
    assert "${module.api.execution_arn}" in main_tf


def test_lambda_permission_source_arn_scopes_to_the_exact_route():
    main_tf = _render(_spec(route=RouteSpec(method=HttpMethod.POST, path="/orders")))
    assert '"${module.api.execution_arn}/$default/POST/orders"' in main_tf


def test_lambda_permission_statement_id_is_derived_from_the_composition_name():
    main_tf = _render(_spec(name="checkout-worker"))
    assert '"checkout-worker-apigateway-invoke"' in main_tf


def test_lambda_permission_never_modifies_the_execution_role():
    """Critical IAM distinction: the invocation grant is a Lambda
    resource-based permission, never a change to the execution role
    (which the trusted Lambda module owns exclusively)."""
    main_tf = _render(_spec())
    assert "aws_iam_role_policy" not in main_tf
    assert "policy_attachment" not in main_tf


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_the_same_spec_twice_is_byte_identical():
    spec = _spec()
    first = ApiLambdaTerraformRenderer().render(spec, module_sources=_SOURCES)
    second = ApiLambdaTerraformRenderer().render(spec, module_sources=_SOURCES)
    assert first.files == second.files

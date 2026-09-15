"""Unit tests for the API Gateway (HTTP API) Terraform renderer (Phase
2, Batch 20).

Real `terraform fmt`/`init`/`validate`/`plan` proof lives in
`tests/integration/test_api_gateway_renderer_terraform.py`, not here —
this suite never shells out to any binary.
"""

from __future__ import annotations

from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.api_gateway.renderer import ApiGatewayTerraformCompositionRenderer

_MODULE_SOURCE = "../../terraform/modules/api_gateway"


def _render(spec: ApiGatewayResourceSpec, module_source: str = _MODULE_SOURCE):
    composition = ApiGatewayTerraformCompositionRenderer().render(spec, module_source=module_source)
    return composition.files["main.tf"]


def test_output_is_exactly_main_tf_and_versions_tf():
    composition = ApiGatewayTerraformCompositionRenderer().render(
        ApiGatewayResourceSpec(name="orders-api"), module_source=_MODULE_SOURCE
    )
    assert set(composition.files) == {"main.tf", "versions.tf"}


def test_never_emits_a_raw_apigatewayv2_resource_block():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api"))
    assert 'resource "aws_apigatewayv2_api"' not in main_tf
    assert 'resource "aws_apigatewayv2_stage"' not in main_tf


def test_instantiates_the_trusted_module():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api"))
    assert 'module "api" {' in main_tf
    assert f'source = "{_MODULE_SOURCE}"' in main_tf


def test_reflects_the_spec_name_and_description():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api", description="Orders API"))
    assert 'name        = "orders-api"' in main_tf
    assert 'description = "Orders API"' in main_tf


def test_description_omitted_renders_as_null():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api"))
    assert "description = null" in main_tf


def test_empty_tags_render_as_plain_empty_map():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api"))
    assert "tags        = {}" in main_tf


def test_custom_tags_are_rendered():
    main_tf = _render(ApiGatewayResourceSpec(name="orders-api", tags={"Service": "orders"}))
    assert '"Service" = "orders"' in main_tf


def test_rendering_the_same_spec_twice_is_byte_identical():
    spec = ApiGatewayResourceSpec(name="orders-api", description="Orders API", tags={"A": "b"})
    renderer = ApiGatewayTerraformCompositionRenderer()
    first = renderer.render(spec, module_source=_MODULE_SOURCE)
    second = renderer.render(spec, module_source=_MODULE_SOURCE)
    assert first.files == second.files


def test_default_module_source_is_used_when_not_overridden():
    composition = ApiGatewayTerraformCompositionRenderer().render(
        ApiGatewayResourceSpec(name="orders-api")
    )
    assert _MODULE_SOURCE in composition.files["main.tf"]

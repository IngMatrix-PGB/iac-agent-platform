"""Deterministic Terraform composition renderer for the API-Gateway-
HTTP-API-to-Lambda-to-DynamoDB architecture (Batch 26).

Converts a validated `ApiLambdaDynamoDbSpec` into a small, self-
contained root Terraform composition that instantiates the three
already-existing trusted modules (`terraform/modules/api_gateway`,
`terraform/modules/lambda`, `terraform/modules/dynamodb`) side by side
and binds them together by combining two techniques already proven
independently elsewhere in this project, unchanged:

  - The API-Gateway-integration/route/Lambda-permission rendering,
    reused verbatim in technique from
    `iac_agent.compositions.api_lambda.renderer` (same fixed
    `AWS_PROXY`/`"2.0"`/`apigateway.amazonaws.com` constants, same
    execute-api ARN scoping grammar). See that module's own docstring
    for the full rationale — not repeated here.
  - The DynamoDB write-scope IAM binding, reused verbatim in technique
    from `iac_agent.compositions.serverless_worker.renderer` ("Option
    B": a composition-owned `aws_iam_role_policy` attached to the
    trusted Lambda module's own `execution_role_name` output — the
    Lambda module's baseline behavior is completely unchanged). Batch
    26's closed design decision restricts the grant to exactly
    `dynamodb:PutItem` — never a broader or wildcard action set.

This module never emits a raw `aws_apigatewayv2_api`,
`aws_apigatewayv2_stage`, `aws_lambda_function`, `aws_iam_role`, or
`aws_dynamodb_table` resource block — those remain exclusively owned by
the trusted modules. No network calls, no filesystem I/O, no subprocess
execution. The same validated spec always renders to byte-identical
output.
"""

from __future__ import annotations

from dataclasses import dataclass

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_bool,
    hcl_number,
    hcl_optional_number,
    hcl_optional_string,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import ApiLambdaDynamoDbSpec

# -- API Gateway integration / route / Lambda permission — fixed,
# non-caller-configurable constants, identical to
# iac_agent.compositions.api_lambda.renderer's own values.

_INTEGRATION_TYPE = "AWS_PROXY"
_INTEGRATION_METHOD = "POST"
_PAYLOAD_FORMAT_VERSION = "2.0"
_INVOKE_PRINCIPAL = "apigateway.amazonaws.com"
_INVOKE_ACTION = "lambda:InvokeFunction"
_STAGE_NAME = "$default"

#: Batch 26 closed decision: exactly one DynamoDB write action, never a
#: broader or wildcard set. Additional DynamoDB behavior requires a
#: future, separate architecture decision.
_DYNAMODB_WRITE_ACTIONS = ("dynamodb:PutItem",)


@dataclass(frozen=True)
class ApiLambdaDynamoDbModuleSources:
    """The three trusted-module `source` values this composition needs.

    A plain, explicit trio — not a `dict[str, str]` — so a caller can
    never accidentally supply a source for a module this composition
    doesn't have.
    """

    api: str
    function: str
    table: str


def _module_attr_line(key: str, value: str, width: int) -> str:
    return f"  {key.ljust(width)} = {value}\n"


def _isolated_attr_line(key: str, value: str) -> str:
    return f"  {key} = {value}\n"


_API_MODULE_KEYS = ("name", "description")
_API_MODULE_WIDTH = max(len(key) for key in _API_MODULE_KEYS)

_FUNCTION_MODULE_KEYS = (
    "name",
    "handler",
    "runtime",
    "architecture",
    "memory_size_mb",
    "timeout_seconds",
    "reserved_concurrency",
    "tracing_mode",
    "log_retention_days",
)
_FUNCTION_MODULE_WIDTH = max(len(key) for key in _FUNCTION_MODULE_KEYS)

_TABLE_MODULE_KEYS = (
    "name",
    "hash_key_name",
    "hash_key_type",
    "range_key_name",
    "range_key_type",
    "point_in_time_recovery",
    "deletion_protection",
)
_TABLE_MODULE_WIDTH = max(len(key) for key in _TABLE_MODULE_KEYS)


def _merged_tags_hcl(composition_tags: dict[str, str], sub_tags: dict[str, str]) -> str:
    return hcl_tags({**composition_tags, **sub_tags})


def _render_api_module_block(spec: ApiLambdaDynamoDbSpec, source: str) -> str:
    api = spec.api
    tags_hcl = _merged_tags_hcl(spec.tags, api.tags)
    tags_line = (
        _module_attr_line("tags", tags_hcl, _API_MODULE_WIDTH)
        if "\n" not in tags_hcl
        else _isolated_attr_line("tags", tags_hcl)
    )
    return (
        'module "api" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(api.name), _API_MODULE_WIDTH)
        + _module_attr_line("description", hcl_optional_string(api.description), _API_MODULE_WIDTH)
        + tags_line
        + "}\n"
    )


def _render_function_module_block(spec: ApiLambdaDynamoDbSpec, source: str) -> str:
    function = spec.function
    env_hcl = hcl_tags(function.environment_variables)
    tags_hcl = _merged_tags_hcl(spec.tags, function.tags)
    env_is_single_line = "\n" not in env_hcl
    tags_is_single_line = "\n" not in tags_hcl

    group_keys = list(_FUNCTION_MODULE_KEYS)
    if env_is_single_line:
        group_keys.append("environment_variables")
        if tags_is_single_line:
            group_keys.append("tags")
    group_width = max(len(key) for key in group_keys)

    env_line = (
        _module_attr_line("environment_variables", env_hcl, group_width)
        if env_is_single_line
        else _isolated_attr_line("environment_variables", env_hcl)
    )
    if tags_is_single_line:
        tags_width = group_width if env_is_single_line else len("tags")
        tags_line = _module_attr_line("tags", tags_hcl, tags_width)
    else:
        tags_line = _isolated_attr_line("tags", tags_hcl)

    return (
        'module "function" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(function.name), group_width)
        + _module_attr_line("handler", hcl_string(function.handler), group_width)
        + _module_attr_line("runtime", hcl_string(function.runtime.value), group_width)
        + _module_attr_line("architecture", hcl_string(function.architecture.value), group_width)
        + _module_attr_line("memory_size_mb", hcl_number(function.memory_size_mb), group_width)
        + _module_attr_line("timeout_seconds", hcl_number(function.timeout_seconds), group_width)
        + _module_attr_line(
            "reserved_concurrency",
            hcl_optional_number(function.reserved_concurrency),
            group_width,
        )
        + _module_attr_line("tracing_mode", hcl_string(function.tracing_mode.value), group_width)
        + _module_attr_line(
            "log_retention_days", hcl_number(function.log_retention_days), group_width
        )
        + env_line
        + tags_line
        + "}\n"
    )


def _render_table_module_block(spec: ApiLambdaDynamoDbSpec, source: str) -> str:
    table = spec.table
    sort_key_name = table.sort_key.name if table.sort_key is not None else None
    sort_key_type = table.sort_key.type.value if table.sort_key is not None else None
    tags_hcl = _merged_tags_hcl(spec.tags, table.tags)
    tags_line = (
        _module_attr_line("tags", tags_hcl, _TABLE_MODULE_WIDTH)
        if "\n" not in tags_hcl
        else _isolated_attr_line("tags", tags_hcl)
    )
    return (
        'module "table" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(table.name), _TABLE_MODULE_WIDTH)
        + _module_attr_line(
            "hash_key_name", hcl_string(table.partition_key.name), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "hash_key_type", hcl_string(table.partition_key.type.value), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "range_key_name", hcl_optional_string(sort_key_name), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "range_key_type", hcl_optional_string(sort_key_type), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "point_in_time_recovery",
            hcl_bool(table.point_in_time_recovery),
            _TABLE_MODULE_WIDTH,
        )
        + _module_attr_line(
            "deletion_protection", hcl_bool(table.deletion_protection), _TABLE_MODULE_WIDTH
        )
        + tags_line
        + "}\n"
    )


def _render_integration_block() -> str:
    return (
        'resource "aws_apigatewayv2_integration" "lambda" {\n'
        "  api_id                 = module.api.api_id\n"
        f"  integration_type       = {hcl_string(_INTEGRATION_TYPE)}\n"
        f"  integration_method     = {hcl_string(_INTEGRATION_METHOD)}\n"
        "  integration_uri        = module.function.function_arn\n"
        f"  payload_format_version = {hcl_string(_PAYLOAD_FORMAT_VERSION)}\n"
        "}\n"
    )


def _render_route_block(spec: ApiLambdaDynamoDbSpec) -> str:
    return (
        'resource "aws_apigatewayv2_route" "this" {\n'
        "  api_id    = module.api.api_id\n"
        f"  route_key = {hcl_string(spec.route.route_key)}\n"
        '  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"\n'
        "}\n"
    )


def _render_lambda_permission_block(spec: ApiLambdaDynamoDbSpec) -> str:
    method = spec.route.method.value
    path = spec.route.path
    source_arn_expr = (
        f'"${{module.api.execution_arn}}/{_STAGE_NAME}/{method}{path}"'
        if path != "/"
        else f'"${{module.api.execution_arn}}/{_STAGE_NAME}/{method}/"'
    )
    return (
        'resource "aws_lambda_permission" "api_gateway" {\n'
        f"  statement_id  = {hcl_string(f'{spec.name}-apigateway-invoke')}\n"
        f"  action        = {hcl_string(_INVOKE_ACTION)}\n"
        "  function_name = module.function.function_name\n"
        f"  principal     = {hcl_string(_INVOKE_PRINCIPAL)}\n"
        f"  source_arn    = {source_arn_expr}\n"
        "}\n"
    )


def _render_dynamodb_write_policy_block(spec: ApiLambdaDynamoDbSpec) -> str:
    actions_hcl = ",\n".join(f'      "{action}"' for action in _DYNAMODB_WRITE_ACTIONS)
    return (
        'data "aws_iam_policy_document" "dynamodb_write" {\n'
        "  statement {\n"
        '    effect = "Allow"\n'
        "    actions = [\n"
        f"{actions_hcl},\n"
        "    ]\n"
        "    resources = [module.table.table_arn]\n"
        "  }\n"
        "}\n"
        "\n"
        'resource "aws_iam_role_policy" "dynamodb_write" {\n'
        f"  name   = {hcl_string(f'{spec.name}-dynamodb-write')}\n"
        "  role   = module.function.execution_role_name\n"
        "  policy = data.aws_iam_policy_document.dynamodb_write.json\n"
        "}\n"
    )


def _render_main_tf(
    spec: ApiLambdaDynamoDbSpec, module_sources: ApiLambdaDynamoDbModuleSources
) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by ApiLambdaDynamoDbTerraformRenderer from a\n"
        "# validated ApiLambdaDynamoDbSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_api_module_block(spec, module_sources.api)
        + "\n"
        + _render_function_module_block(spec, module_sources.function)
        + "\n"
        + _render_table_module_block(spec, module_sources.table)
        + "\n"
        + _render_integration_block()
        + "\n"
        + _render_route_block(spec)
        + "\n"
        + _render_lambda_permission_block(spec)
        + "\n"
        + _render_dynamodb_write_policy_block(spec)
    )


class ApiLambdaDynamoDbTerraformRenderer:
    """Renders a validated `ApiLambdaDynamoDbSpec` into a root Terraform
    composition instantiating the trusted API Gateway, Lambda, and
    DynamoDB modules plus the relationship resources that bind them.

    Holds no state and performs no I/O — safe to instantiate once and
    reuse. Produces exactly `main.tf` + `versions.tf`, matching every
    other renderer's output shape.
    """

    def render(
        self,
        spec: ApiLambdaDynamoDbSpec,
        *,
        module_sources: ApiLambdaDynamoDbModuleSources,
    ) -> GeneratedTerraformComposition:
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_sources),
            }
        )

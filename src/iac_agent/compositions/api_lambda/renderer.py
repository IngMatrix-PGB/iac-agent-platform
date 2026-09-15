"""Deterministic Terraform composition renderer for the API-Gateway-
HTTP-API-to-Lambda architecture (Phase 2, Batch 20).

Converts a validated `ApiLambdaSpec` into a small, self-contained root
Terraform composition that instantiates the two already-existing
trusted modules (`terraform/modules/api_gateway`,
`terraform/modules/lambda`) side by side and binds them together with
exactly three composition-owned relationship resources — none of which
is naturally owned by either trusted module alone:

  - `aws_apigatewayv2_integration` — the Lambda proxy integration
    (`AWS_PROXY`, payload format `2.0`).
  - `aws_apigatewayv2_route` — the one explicit `METHOD /path` route
    this composition's contract requires; never an implicit `$default`
    catch-all route.
  - `aws_lambda_permission` — a **Lambda resource-based permission**
    (never a change to the Lambda execution role) allowing exactly
    `apigateway.amazonaws.com` to call `lambda:InvokeFunction`, scoped
    to this API's own execution ARN, stage, method, and path.

This is "Option B" from Batch 19's IAM design pattern, reused here
unchanged: the trusted Lambda module's own baseline behavior (its
CloudWatch Logs execution-role permissions) is completely untouched by
this composition — the API Gateway invocation grant is a wholly
separate mechanism (a resource-based policy on the Lambda function
itself, not a role permission), and this renderer never adds anything
to `module.function`'s own execution role.

This module never emits a raw `aws_apigatewayv2_api`,
`aws_apigatewayv2_stage`, `aws_lambda_function`, or `aws_iam_role`
resource block — those remain exclusively owned by the trusted
modules. No network calls, no filesystem I/O, no subprocess execution.
The same validated spec always renders to byte-identical output.
"""

from __future__ import annotations

from dataclasses import dataclass

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_number,
    hcl_optional_number,
    hcl_optional_string,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import ApiLambdaSpec

#: API Gateway v2 Lambda proxy integration — fixed, non-caller-
#: configurable constants. `integration_method` is always `"POST"`:
#: this is the HTTP method API Gateway itself uses to call the Lambda
#: Invoke API internally, independent of the route's own client-facing
#: method (GET/POST/PUT/PATCH/DELETE).
_INTEGRATION_TYPE = "AWS_PROXY"
_INTEGRATION_METHOD = "POST"
_PAYLOAD_FORMAT_VERSION = "2.0"

#: The exact principal/action `aws_lambda_permission` grants — fixed,
#: reviewed constants, never a caller-configurable field. Verified
#: against current AWS documentation (API Gateway's own service
#: principal for invoking downstream integrations).
_INVOKE_PRINCIPAL = "apigateway.amazonaws.com"
_INVOKE_ACTION = "lambda:InvokeFunction"

#: API Gateway v2's own execute-api ARN grammar for scoping an
#: invocation permission to one specific stage/method/path:
#: `<execution_arn>/<stage>/<method><path>` — verified against current
#: AWS documentation/CLI reference. `$default` is the one stage this
#: batch's trusted API Gateway module ever creates (see
#: `terraform/modules/api_gateway`).
_STAGE_NAME = "$default"


@dataclass(frozen=True)
class ApiLambdaModuleSources:
    """The two trusted-module `source` values this composition needs.

    A plain, explicit pair — not a `dict[str, str]` — so a caller can
    never accidentally supply a source for a module this composition
    doesn't have.
    """

    api: str
    function: str


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


def _render_api_module_block(spec: ApiLambdaSpec, source: str) -> str:
    api = spec.api
    tags_hcl = hcl_tags({**spec.tags, **api.tags})
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


def _render_function_module_block(spec: ApiLambdaSpec, source: str) -> str:
    function = spec.function
    env_hcl = hcl_tags(function.environment_variables)
    tags_hcl = hcl_tags({**spec.tags, **function.tags})
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


def _render_route_block(spec: ApiLambdaSpec) -> str:
    return (
        'resource "aws_apigatewayv2_route" "this" {\n'
        "  api_id    = module.api.api_id\n"
        f"  route_key = {hcl_string(spec.route.route_key)}\n"
        '  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"\n'
        "}\n"
    )


def _render_lambda_permission_block(spec: ApiLambdaSpec) -> str:
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


def _render_main_tf(spec: ApiLambdaSpec, module_sources: ApiLambdaModuleSources) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by ApiLambdaTerraformRenderer from a\n"
        "# validated ApiLambdaSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_api_module_block(spec, module_sources.api)
        + "\n"
        + _render_function_module_block(spec, module_sources.function)
        + "\n"
        + _render_integration_block()
        + "\n"
        + _render_route_block(spec)
        + "\n"
        + _render_lambda_permission_block(spec)
    )


class ApiLambdaTerraformRenderer:
    """Renders a validated `ApiLambdaSpec` into a root Terraform
    composition instantiating the trusted API Gateway and Lambda
    modules plus the relationship resources that bind them.

    Holds no state and performs no I/O — safe to instantiate once and
    reuse. Produces exactly `main.tf` + `versions.tf`, matching every
    other renderer's output shape.
    """

    def render(
        self,
        spec: ApiLambdaSpec,
        *,
        module_sources: ApiLambdaModuleSources,
    ) -> GeneratedTerraformComposition:
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_sources),
            }
        )

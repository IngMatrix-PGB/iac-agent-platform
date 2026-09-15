"""Deterministic API Gateway (HTTP API) Terraform composition renderer
(Phase 2, Batch 20).

Converts a validated `ApiGatewayResourceSpec` into a small, self-
contained root Terraform composition that instantiates the trusted
`terraform/modules/api_gateway` module — the API Gateway counterpart to
`iac_agent.providers.aws.sqs.renderer` /
`.s3.renderer` / `.dynamodb.renderer` / `.lambda_function.renderer`.
Never emits a raw `aws_apigatewayv2_api`/`aws_apigatewayv2_stage`
resource block directly, only a `module` block. No network calls, no
filesystem I/O, no subprocess execution. The same validated spec always
renders to byte-identical output.

Shared, resource-agnostic HCL-rendering primitives live in
`iac_agent.providers.aws.terraform_render` and are reused as-is here —
see that module's docstring.
"""

from __future__ import annotations

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_optional_string,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import ApiGatewayResourceSpec

#: Module source assumed for the production convention — mirrors
#: `iac_agent.providers.aws.dynamodb.renderer.DEFAULT_MODULE_SOURCE`
#: exactly.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/api_gateway"

_MODULE_ATTRIBUTE_KEYS = ("name", "description")
_MODULE_ATTRIBUTE_WIDTH = max(len(key) for key in _MODULE_ATTRIBUTE_KEYS)


def _attr_line(key: str, value: str) -> str:
    return f"  {key.ljust(_MODULE_ATTRIBUTE_WIDTH)} = {value}\n"


def _render_module_block(spec: ApiGatewayResourceSpec, module_source: str) -> str:
    tags_hcl = hcl_tags(spec.tags)
    tags_line = _attr_line("tags", tags_hcl) if "\n" not in tags_hcl else f"  tags = {tags_hcl}\n"

    return (
        'module "api" {\n'
        f"  source = {hcl_string(module_source)}\n\n"
        + _attr_line("name", hcl_string(spec.name))
        + _attr_line("description", hcl_optional_string(spec.description))
        + tags_line
        + "}\n"
    )


def _render_main_tf(spec: ApiGatewayResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by ApiGatewayTerraformCompositionRenderer from a\n"
        "# validated ApiGatewayResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class ApiGatewayTerraformCompositionRenderer:
    """Renders a validated `ApiGatewayResourceSpec` into a root
    Terraform composition that instantiates the trusted API Gateway
    module.

    This class holds no state and performs no I/O — safe to
    instantiate once and reuse.
    """

    def render(
        self,
        spec: ApiGatewayResourceSpec,
        *,
        module_source: str = DEFAULT_MODULE_SOURCE,
    ) -> GeneratedTerraformComposition:
        """Render `spec` into a deterministic set of Terraform files.

        `module_source` defaults to the production convention but must
        be overridden by any caller writing the composition to a
        differently-shaped directory (for example, an integration test
        workspace). Never inspects the filesystem, the process working
        directory, or the local environment.
        """
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_source),
            }
        )

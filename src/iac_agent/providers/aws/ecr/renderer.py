"""Deterministic ECR Terraform composition renderer (Batch 27).

Converts a validated EcrResourceSpec into a root composition that
instantiates terraform/modules/ecr. Never emits a raw
aws_ecr_repository block. Encryption stays inside the trusted module.
"""

from __future__ import annotations

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_bool,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import EcrResourceSpec

DEFAULT_MODULE_SOURCE = "../../terraform/modules/ecr"


def _render_module_block(spec: EcrResourceSpec, module_source: str) -> str:
    tags_hcl = hcl_tags(spec.tags)
    tags_line = (
        f"  tags                 = {tags_hcl}\n"
        if "\n" not in tags_hcl
        else f"  tags = {tags_hcl}\n"
    )
    return (
        'module "ecr" {\n'
        f"  source               = {hcl_string(module_source)}\n\n"
        f"  name                 = {hcl_string(spec.name)}\n"
        f"  image_tag_mutability = {hcl_string(spec.image_tag_mutability.value)}\n"
        f"  scan_on_push         = {hcl_bool(spec.scan_on_push)}\n"
        f"{tags_line}"
        "}\n"
    )


def _render_main_tf(spec: EcrResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by EcrTerraformCompositionRenderer from a\n"
        "# validated EcrResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class EcrTerraformCompositionRenderer:
    """Renders a validated EcrResourceSpec into a root Terraform composition."""

    def render(
        self,
        spec: EcrResourceSpec,
        *,
        module_source: str = DEFAULT_MODULE_SOURCE,
    ) -> GeneratedTerraformComposition:
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_source),
            }
        )

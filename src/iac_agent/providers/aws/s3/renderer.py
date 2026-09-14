"""Deterministic S3 Terraform composition renderer (Phase 2).

Converts a validated ``S3ResourceSpec`` into a small, self-contained
root Terraform composition that instantiates the trusted
``terraform/modules/s3`` module — the S3 counterpart to
``iac_agent.providers.aws.sqs.renderer``. Never emits a raw
``aws_s3_*`` resource block directly, only a ``module`` block. No
network calls, no filesystem I/O, no subprocess execution. The same
validated spec always renders to byte-identical output.

Shared, resource-agnostic HCL-rendering primitives live in
`iac_agent.providers.aws.terraform_render` and are reused as-is here —
see that module's docstring.
"""

from __future__ import annotations

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_bool,
    hcl_optional_string,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import S3ResourceSpec

#: Module source assumed for the production convention — mirrors
#: `iac_agent.providers.aws.sqs.renderer.DEFAULT_MODULE_SOURCE` exactly.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/s3"


def _render_module_block(spec: S3ResourceSpec, module_source: str) -> str:
    tags_hcl = hcl_tags(spec.tags)
    tags_line = f"  tags       = {tags_hcl}\n" if "\n" not in tags_hcl else f"  tags = {tags_hcl}\n"

    return (
        'module "bucket" {\n'
        f"  source = {hcl_string(module_source)}\n\n"
        f"  name       = {hcl_string(spec.name)}\n"
        f"  kms_key_id = {hcl_optional_string(spec.encryption.kms_key_id)}\n"
        f"  versioning = {hcl_bool(spec.versioning)}\n"
        f"{tags_line}"
        "}\n"
    )


def _render_main_tf(spec: S3ResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by S3TerraformCompositionRenderer from a\n"
        "# validated S3ResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class S3TerraformCompositionRenderer:
    """Renders a validated ``S3ResourceSpec`` into a root Terraform
    composition that instantiates the trusted S3 module.

    This class holds no state and performs no I/O — safe to instantiate
    once and reuse.
    """

    def render(
        self,
        spec: S3ResourceSpec,
        *,
        module_source: str = DEFAULT_MODULE_SOURCE,
    ) -> GeneratedTerraformComposition:
        """Render ``spec`` into a deterministic set of Terraform files.

        ``module_source`` defaults to the production convention but
        must be overridden by any caller writing the composition to a
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

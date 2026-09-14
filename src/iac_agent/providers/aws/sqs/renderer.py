"""Deterministic SQS Terraform composition renderer.

Converts a validated ``SQSResourceSpec`` into a small, self-contained
root Terraform composition that instantiates the trusted
``terraform/modules/sqs`` module. This module never emits an
``aws_sqs_queue`` (or any other ``aws_*``) resource block directly —
only a ``module`` block. It performs no network calls, no filesystem
I/O, no subprocess execution, and imports nothing from LangChain or
LangGraph. The same validated spec always renders to byte-identical
output.

Shared, resource-agnostic HCL-rendering primitives (string/bool/number
escaping, tag-map rendering, the credential-free provider block, the
versions block) live in `iac_agent.providers.aws.terraform_render` and
are reused as-is here — see that module's docstring for why (Phase 2
introduced the S3 renderer, which needs byte-identical versions/
provider boilerplate).
"""

from __future__ import annotations

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

from .contract import SQSResourceSpec

#: Module source assumed for the production convention, where a
#: generated composition lives at ``artifacts/<request_id>/`` (two
#: directories below the repository root) and the trusted module lives
#: at ``terraform/modules/sqs``. Callers writing to a different
#: directory depth (for example, an integration test workspace) must
#: pass an explicit ``module_source`` instead of relying on this
#: default — the renderer never inspects the filesystem to infer it.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/sqs"


def _render_module_block(spec: SQSResourceSpec, module_source: str) -> str:
    tags_hcl = hcl_tags(spec.tags)
    # terraform fmt does not align "=" for an attribute whose value spans
    # multiple lines (a non-empty tags map) with the single-line
    # attributes around it — matching that exactly here keeps the raw
    # renderer output already canonically formatted, with no separate
    # `terraform fmt` pass required.
    tags_line = (
        f"  tags                       = {tags_hcl}\n"
        if "\n" not in tags_hcl
        else f"  tags = {tags_hcl}\n"
    )

    return (
        'module "queue" {\n'
        f"  source = {hcl_string(module_source)}\n\n"
        f"  name                       = {hcl_string(spec.name)}\n"
        f"  fifo                       = {hcl_bool(spec.fifo)}\n"
        f"  visibility_timeout_seconds = {hcl_number(spec.visibility_timeout_seconds)}\n"
        f"  message_retention_seconds  = {hcl_number(spec.message_retention_seconds)}\n"
        f"  delay_seconds              = {hcl_number(spec.delay_seconds)}\n"
        f"  kms_key_id                 = {hcl_optional_string(spec.encryption.kms_key_id)}\n"
        f"  dlq_enabled                = {hcl_bool(spec.dlq.enabled)}\n"
        f"  max_receive_count          = {hcl_optional_number(spec.dlq.max_receive_count)}\n"
        f"{tags_line}"
        "}\n"
    )


def _render_main_tf(spec: SQSResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by TerraformCompositionRenderer from a\n"
        "# validated SQSResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class TerraformCompositionRenderer:
    """Renders a validated ``SQSResourceSpec`` into a root Terraform
    composition that instantiates the trusted SQS module.

    This class holds no state and performs no I/O — it is safe to
    instantiate once and reuse, or to call the equivalent module-level
    behavior repeatedly with identical results.
    """

    def render(
        self,
        spec: SQSResourceSpec,
        *,
        module_source: str = DEFAULT_MODULE_SOURCE,
    ) -> GeneratedTerraformComposition:
        """Render ``spec`` into a deterministic set of Terraform files.

        ``module_source`` defaults to the production convention
        (``artifacts/<request_id>/`` two directories below the trusted
        module) but must be overridden by any caller writing the
        composition to a differently-shaped directory, such as an
        integration test workspace. This function never inspects the
        filesystem, the current working directory, or the local
        environment to determine or adjust the path.
        """
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_source),
            }
        )

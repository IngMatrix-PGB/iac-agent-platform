"""Deterministic DynamoDB Terraform composition renderer (Phase 2,
Batch 17).

Converts a validated ``DynamoDBResourceSpec`` into a small, self-
contained root Terraform composition that instantiates the trusted
``terraform/modules/dynamodb`` module — the DynamoDB counterpart to
``iac_agent.providers.aws.sqs.renderer`` /
``iac_agent.providers.aws.s3.renderer``. Never emits a raw
``aws_dynamodb_table`` resource block directly, only a ``module``
block. No network calls, no filesystem I/O, no subprocess execution.
The same validated spec always renders to byte-identical output.

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

from .contract import DynamoDBResourceSpec

#: Module source assumed for the production convention — mirrors
#: `iac_agent.providers.aws.s3.renderer.DEFAULT_MODULE_SOURCE` exactly.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/dynamodb"


#: Every single-line attribute in the module block's first group
#: (everything except `source`, which stands alone before a blank
#: line, and `tags`, rendered separately below). Real `terraform fmt`
#: aligns the "=" of every attribute in one contiguous group to the
#: widest key's column — verified empirically (see the `hcl_tags`
#: docstring for the identical discovery in the tag-map case) — so
#: this width is computed once from the fixed key set below rather
#: than guessed at.
#: No `kms_key_id` attribute is rendered at all — see
#: `DynamoDBEncryptionSpec`'s docstring for why customer-managed KMS
#: support is deferred to a future phase rather than wired up here;
#: this phase always uses AWS-owned-key encryption.
_MODULE_ATTRIBUTE_KEYS = (
    "name",
    "hash_key_name",
    "hash_key_type",
    "range_key_name",
    "range_key_type",
    "point_in_time_recovery",
    "deletion_protection",
)
_MODULE_ATTRIBUTE_WIDTH = max(len(key) for key in _MODULE_ATTRIBUTE_KEYS)


def _attr_line(key: str, value: str) -> str:
    return f"  {key.ljust(_MODULE_ATTRIBUTE_WIDTH)} = {value}\n"


def _render_module_block(spec: DynamoDBResourceSpec, module_source: str) -> str:
    tags_hcl = hcl_tags(spec.tags)
    tags_line = _attr_line("tags", tags_hcl) if "\n" not in tags_hcl else f"  tags = {tags_hcl}\n"

    sort_key_name = spec.sort_key.name if spec.sort_key is not None else None
    sort_key_type = spec.sort_key.type.value if spec.sort_key is not None else None

    return (
        'module "dynamodb" {\n'
        f"  source = {hcl_string(module_source)}\n\n"
        + _attr_line("name", hcl_string(spec.name))
        + _attr_line("hash_key_name", hcl_string(spec.partition_key.name))
        + _attr_line("hash_key_type", hcl_string(spec.partition_key.type.value))
        + _attr_line("range_key_name", hcl_optional_string(sort_key_name))
        + _attr_line("range_key_type", hcl_optional_string(sort_key_type))
        + _attr_line("point_in_time_recovery", hcl_bool(spec.point_in_time_recovery))
        + _attr_line("deletion_protection", hcl_bool(spec.deletion_protection))
        + tags_line
        + "}\n"
    )


def _render_main_tf(spec: DynamoDBResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by DynamoDBTerraformCompositionRenderer from a\n"
        "# validated DynamoDBResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class DynamoDBTerraformCompositionRenderer:
    """Renders a validated ``DynamoDBResourceSpec`` into a root Terraform
    composition that instantiates the trusted DynamoDB module.

    This class holds no state and performs no I/O — safe to instantiate
    once and reuse.
    """

    def render(
        self,
        spec: DynamoDBResourceSpec,
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

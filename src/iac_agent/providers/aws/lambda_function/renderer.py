"""Deterministic Lambda Terraform composition renderer (Phase 2,
Batch 18).

Converts a validated ``LambdaResourceSpec`` into a small, self-
contained root Terraform composition that instantiates the trusted
``terraform/modules/lambda`` module — the Lambda counterpart to
``iac_agent.providers.aws.sqs.renderer`` /
``iac_agent.providers.aws.s3.renderer`` /
``iac_agent.providers.aws.dynamodb.renderer``. Never emits a raw
``aws_lambda_function``, ``aws_iam_role``, ``aws_iam_role_policy``, or
``aws_cloudwatch_log_group`` resource block directly, only a
``module`` block — those all belong inside the trusted module. No
network calls, no filesystem I/O, no subprocess execution. The same
validated spec always renders to byte-identical output.

Shared, resource-agnostic HCL-rendering primitives live in
`iac_agent.providers.aws.terraform_render` and are reused as-is here —
see that module's docstring.
"""

from __future__ import annotations

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_number,
    hcl_optional_number,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import LambdaResourceSpec

#: Module source assumed for the production convention — mirrors
#: `iac_agent.providers.aws.dynamodb.renderer.DEFAULT_MODULE_SOURCE`
#: exactly.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/lambda"

#: The attributes that are *always* single-line scalars, and therefore
#: always part of one contiguous `terraform fmt` alignment group.
#: `environment_variables` and `tags` join this same group only when
#: their map happens to be empty (rendering as `= {}` on one line); a
#: non-empty map renders as a multi-line block, which breaks the group
#: instead. Real `terraform fmt` aligns the "=" of every attribute in
#: one contiguous group to the *widest* key's column — verified
#: empirically (see the `hcl_tags` docstring for the identical
#: discovery in the tag-map case) — so each render computes the
#: group's width from exactly the keys that will actually appear in it,
#: rather than a single guessed-at constant.
_ALWAYS_SINGLE_LINE_KEYS = (
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


def _hcl_string_map(values: dict[str, str]) -> str:
    """Render a plain string->string map deterministically, reusing the
    same sorted-order/alignment discipline as `hcl_tags` (tags and
    environment variables are rendered identically; this is a thin,
    intentional wrapper rather than a re-copy of that logic)."""
    return hcl_tags(values)


def _render_module_block(spec: LambdaResourceSpec, module_source: str) -> str:
    env_hcl = _hcl_string_map(spec.environment_variables)
    tags_hcl = hcl_tags(spec.tags)
    env_is_single_line = "\n" not in env_hcl
    tags_is_single_line = "\n" not in tags_hcl

    # `environment_variables` immediately follows the always-single-line
    # base attributes, so it only extends that same contiguous
    # `terraform fmt` alignment group when it itself renders single-line
    # (an empty map). `tags` comes right after `environment_variables`,
    # so it can only still be part of *that* group if environment_
    # variables didn't already break the chain by going multi-line —
    # otherwise tags is its own isolated single-line entry, needing no
    # padding beyond its own width. Verified empirically against real
    # `terraform fmt` for all four combinations before settling on this.
    group_keys = list(_ALWAYS_SINGLE_LINE_KEYS)
    if env_is_single_line:
        group_keys.append("environment_variables")
        if tags_is_single_line:
            group_keys.append("tags")
    group_width = max(len(key) for key in group_keys)

    def attr_line(key: str, value: str, width: int) -> str:
        return f"  {key.ljust(width)} = {value}\n"

    env_line = (
        attr_line("environment_variables", env_hcl, group_width)
        if env_is_single_line
        else f"  environment_variables = {env_hcl}\n"
    )
    if tags_is_single_line:
        tags_width = group_width if env_is_single_line else len("tags")
        tags_line = attr_line("tags", tags_hcl, tags_width)
    else:
        tags_line = f"  tags = {tags_hcl}\n"

    return (
        'module "lambda" {\n'
        f"  source = {hcl_string(module_source)}\n\n"
        + attr_line("name", hcl_string(spec.name), group_width)
        + attr_line("handler", hcl_string(spec.handler), group_width)
        + attr_line("runtime", hcl_string(spec.runtime.value), group_width)
        + attr_line("architecture", hcl_string(spec.architecture.value), group_width)
        + attr_line("memory_size_mb", hcl_number(spec.memory_size_mb), group_width)
        + attr_line("timeout_seconds", hcl_number(spec.timeout_seconds), group_width)
        + attr_line(
            "reserved_concurrency", hcl_optional_number(spec.reserved_concurrency), group_width
        )
        + attr_line("tracing_mode", hcl_string(spec.tracing_mode.value), group_width)
        + attr_line("log_retention_days", hcl_number(spec.log_retention_days), group_width)
        + env_line
        + tags_line
        + "}\n"
    )


def _render_main_tf(spec: LambdaResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by LambdaTerraformCompositionRenderer from a\n"
        "# validated LambdaResourceSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_module_block(spec, module_source)
    )


class LambdaTerraformCompositionRenderer:
    """Renders a validated ``LambdaResourceSpec`` into a root Terraform
    composition that instantiates the trusted Lambda module.

    This class holds no state and performs no I/O — safe to instantiate
    once and reuse.
    """

    def render(
        self,
        spec: LambdaResourceSpec,
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

"""Deterministic SQS Terraform composition renderer.

Converts a validated ``SQSResourceSpec`` into a small, self-contained
root Terraform composition that instantiates the trusted
``terraform/modules/sqs`` module. This module never emits an
``aws_sqs_queue`` (or any other ``aws_*``) resource block directly —
only a ``module`` block. It performs no network calls, no filesystem
I/O, no subprocess execution, and imports nothing from LangChain or
LangGraph. The same validated spec always renders to byte-identical
output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .contract import SQSResourceSpec

#: Module source assumed for the production convention, where a
#: generated composition lives at ``artifacts/<request_id>/`` (two
#: directories below the repository root) and the trusted module lives
#: at ``terraform/modules/sqs``. Callers writing to a different
#: directory depth (for example, an integration test workspace) must
#: pass an explicit ``module_source`` instead of relying on this
#: default — the renderer never inspects the filesystem to infer it.
DEFAULT_MODULE_SOURCE = "../../terraform/modules/sqs"

_AWS_REGION = "us-east-1"


@dataclass(frozen=True)
class GeneratedTerraformComposition:
    """The deterministic output of rendering one ``SQSResourceSpec``.

    ``files`` maps a relative filename to its full text content. Treat
    it as read-only; nothing in this module mutates it after
    construction.
    """

    files: dict[str, str]

    def write_to(self, directory: Path) -> None:
        """Materialize every generated file under ``directory``.

        This is the only place in this module that touches the
        filesystem, and it is never called implicitly by ``render()`` —
        a caller must invoke it explicitly.
        """
        directory.mkdir(parents=True, exist_ok=True)
        for relative_path, content in self.files.items():
            (directory / relative_path).write_text(content, encoding="utf-8")


def _hcl_string(value: str) -> str:
    """Render a Python string as a safe, quoted HCL string literal.

    Base escaping (backslash, quote, control characters, non-ASCII) is
    delegated to ``json.dumps`` — the HCL string-literal escape grammar
    is a compatible superset of JSON's for these characters, and reusing
    a well-tested stdlib implementation avoids hand-rolling escaping
    logic. HCL additionally treats ``${`` and ``%{`` as the start of a
    template interpolation/directive, so those sequences are escaped a
    second time (``$${`` / ``%%{``) to guarantee arbitrary tag/name text
    can never be interpreted as a template expression.
    """
    escaped = json.dumps(value)
    return escaped.replace("${", "$${").replace("%{", "%%{")


def _hcl_bool(value: bool) -> str:
    return "true" if value else "false"


def _hcl_number(value: int) -> str:
    return str(value)


def _hcl_optional_string(value: str | None) -> str:
    return "null" if value is None else _hcl_string(value)


def _hcl_optional_number(value: int | None) -> str:
    return "null" if value is None else _hcl_number(value)


def _hcl_tags(tags: dict[str, str]) -> str:
    """Render a tag map deterministically, independent of insertion order."""
    if not tags:
        return "{}"
    entries = "\n".join(
        f"    {_hcl_string(key)} = {_hcl_string(value)}" for key, value in sorted(tags.items())
    )
    return f"{{\n{entries}\n  }}"


def _render_versions_tf() -> str:
    # Identical provider/version constraint to the trusted module and the
    # Batch 3 credential-free spike fixture — this is a fixed, spec-
    # independent constant, not re-derived per request.
    return (
        "terraform {\n"
        '  required_version = ">= 1.5.0"\n\n'
        "  required_providers {\n"
        "    aws = {\n"
        '      source  = "hashicorp/aws"\n'
        '      version = "~> 6.0"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )


def _render_provider_block() -> str:
    # Reuses, verbatim, the credential-free provider configuration
    # proven in Batch 3 (docs/terraform-credential-free-plan.md) — no
    # new provider strategy is invented here, and no credentials of any
    # kind (dummy or real) are embedded in generated files.
    return (
        'provider "aws" {\n'
        f"  region = {_hcl_string(_AWS_REGION)}\n\n"
        "  skip_credentials_validation = true\n"
        "  skip_requesting_account_id  = true\n"
        "  skip_metadata_api_check     = true\n"
        "  skip_region_validation      = true\n"
        "}\n"
    )


def _render_module_block(spec: SQSResourceSpec, module_source: str) -> str:
    tags_hcl = _hcl_tags(spec.tags)
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
        f"  source = {_hcl_string(module_source)}\n\n"
        f"  name                       = {_hcl_string(spec.name)}\n"
        f"  fifo                       = {_hcl_bool(spec.fifo)}\n"
        f"  visibility_timeout_seconds = {_hcl_number(spec.visibility_timeout_seconds)}\n"
        f"  message_retention_seconds  = {_hcl_number(spec.message_retention_seconds)}\n"
        f"  delay_seconds              = {_hcl_number(spec.delay_seconds)}\n"
        f"  kms_key_id                 = {_hcl_optional_string(spec.encryption.kms_key_id)}\n"
        f"  dlq_enabled                = {_hcl_bool(spec.dlq.enabled)}\n"
        f"  max_receive_count          = {_hcl_optional_number(spec.dlq.max_receive_count)}\n"
        f"{tags_line}"
        "}\n"
    )


def _render_main_tf(spec: SQSResourceSpec, module_source: str) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by TerraformCompositionRenderer from a\n"
        "# validated SQSResourceSpec. Regenerate instead of modifying.\n\n"
        + _render_provider_block()
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
                "versions.tf": _render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_source),
            }
        )

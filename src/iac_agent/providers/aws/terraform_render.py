"""Shared deterministic Terraform-rendering primitives (Phase 2).

Genuinely resource-agnostic HCL-rendering helpers and the credential-
free provider/version boilerplate — identical between the SQS and S3
renderers (same region, same credential-free provider flags, same
Terraform/provider version constraints), so defined once here rather
than duplicated. Resource-specific renderers
(`iac_agent.providers.aws.sqs.renderer`,
`iac_agent.providers.aws.s3.renderer`) import from this module; neither
re-implements these. No network calls, no filesystem I/O, no
subprocess execution — pure string rendering only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The one AWS region every generated composition's provider block
#: targets. Not user-configurable in Phase 1/2 — the credential-free
#: plan technique (docs/terraform-credential-free-plan.md) never
#: contacts a real region anyway.
AWS_REGION = "us-east-1"


@dataclass(frozen=True)
class GeneratedTerraformComposition:
    """The deterministic output of rendering one validated resource spec.

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


def hcl_string(value: str) -> str:
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


def hcl_bool(value: bool) -> str:
    return "true" if value else "false"


def hcl_number(value: int) -> str:
    return str(value)


def hcl_optional_string(value: str | None) -> str:
    return "null" if value is None else hcl_string(value)


def hcl_optional_number(value: int | None) -> str:
    return "null" if value is None else hcl_number(value)


def hcl_tags(tags: dict[str, str]) -> str:
    """Render a tag map deterministically, independent of insertion order.

    `terraform fmt` aligns the "=" of consecutive attributes in a block
    to the widest key's column — a two-or-more-key map with differently
    sized keys must be pre-aligned here to match, or raw renderer output
    would not already be canonically formatted (discovered via a real
    `terraform fmt -check` run against the SQS renderer with a two-tag,
    different-length-key map; every earlier test used either zero or
    exactly one tag, which never exposes a misalignment).
    """
    if not tags:
        return "{}"
    sorted_items = sorted(tags.items())
    quoted_keys = [hcl_string(key) for key, _ in sorted_items]
    width = max(len(quoted_key) for quoted_key in quoted_keys)
    entries = "\n".join(
        f"    {quoted_key.ljust(width)} = {hcl_string(value)}"
        for quoted_key, (_, value) in zip(quoted_keys, sorted_items, strict=True)
    )
    return f"{{\n{entries}\n  }}"


def render_versions_tf() -> str:
    # Identical provider/version constraint across every trusted module
    # and generated composition — a fixed, spec-independent constant,
    # not re-derived per request.
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


def render_provider_block() -> str:
    # Reuses, verbatim, the credential-free provider configuration
    # proven in Batch 3 (docs/terraform-credential-free-plan.md) — no
    # new provider strategy is invented here, and no credentials of any
    # kind (dummy or real) are embedded in generated files.
    return (
        'provider "aws" {\n'
        f"  region = {hcl_string(AWS_REGION)}\n\n"
        "  skip_credentials_validation = true\n"
        "  skip_requesting_account_id  = true\n"
        "  skip_metadata_api_check     = true\n"
        "  skip_region_validation      = true\n"
        "}\n"
    )

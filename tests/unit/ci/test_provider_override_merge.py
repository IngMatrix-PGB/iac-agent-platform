"""Prove the CI-owned override changes the effective provider configuration
without invoking Terraform.

Terraform's AWS provider validates credentials during Configure whenever
the skip flags are false, including for validate and plan. This test
therefore simulates Terraform's override-merge rule offline: an argument
in an override file replaces that argument in the original provider
block, and an omitted argument is inherited. The original block is an
explicit fixture, not a published request.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROVIDER_FIXTURE = Path("tests/fixtures/provider_aws_skip_flags.tf")
_OVERRIDE_TEMPLATE = Path("ci/aws_plan/provider_override.tf.template")

_SKIP_FLAGS = (
    "skip_credentials_validation",
    "skip_requesting_account_id",
    "skip_metadata_api_check",
    "skip_region_validation",
)


def _strip_comment_lines(text: str) -> str:
    """Comment lines can legitimately contain example HCL snippets (as
    this very template's own header does) — a structural check must
    never let commentary fool it into matching prose instead of real
    configuration."""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _provider_aws_arguments(text: str) -> dict[str, str]:
    text = _strip_comment_lines(text)
    match = re.search(r'provider\s+"aws"\s*\{([^}]*)\}', text, re.DOTALL)
    assert match, "no provider \"aws\" block found"
    body = match.group(1)
    args: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        args[key.strip()] = value.strip()
    return args


def test_provider_fixture_still_has_every_skip_flag_true_unmodified():
    """The fixture keeps the credential-free skip flags. The override
    file is what turns them off."""
    args = _provider_aws_arguments(_PROVIDER_FIXTURE.read_text())
    for flag in _SKIP_FLAGS:
        assert args[flag] == "true"


def test_override_merge_result_has_every_skip_flag_false():
    """Simulates Terraform's own override-merge semantics: arguments
    present in the override completely replace the original's — this
    is the effective configuration Terraform would actually plan with,
    computed without ever invoking the terraform binary."""
    original = _provider_aws_arguments(_PROVIDER_FIXTURE.read_text())
    override = _provider_aws_arguments(_OVERRIDE_TEMPLATE.read_text())

    effective = {**original, **override}  # override wins per Terraform's own merge rule

    for flag in _SKIP_FLAGS:
        assert effective[flag] == "false", f"{flag} was not overridden"


def test_override_does_not_declare_a_resource_module_or_data_block():
    """The override only ever declares a provider "aws" block — it must
    never redeclare a resource/module/data block, which would make it
    generated infrastructure rather than execution-boundary config."""
    text = _OVERRIDE_TEMPLATE.read_text()
    assert not re.search(r'\b(resource|module|data)\s+"', text)

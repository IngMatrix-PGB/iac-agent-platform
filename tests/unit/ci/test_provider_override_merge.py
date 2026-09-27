"""Batch 25, Task 5 (redesigned — see commit message): prove the CI-owned
override actually changes the *effective* provider configuration,
without ever invoking the real `terraform` binary against a merged
config that has the skip-flags disabled.

Why not a real_tool `terraform plan`: Terraform's AWS provider performs
its own credential/account validation during `Configure()` — invoked
for `validate`/`plan` alike — whenever `skip_credentials_validation`/
`skip_requesting_account_id` are `false`. Running that against the
real generated artifact, even with fake `AWS_ACCESS_KEY_ID=test`
credentials, would make Terraform actually attempt a real network call
to AWS's STS endpoint — a genuine AWS API reach, explicitly prohibited
before Task 11/Gate C. Task 5 is therefore a deterministic, offline
simulation of Terraform's own documented override-merge algorithm
instead: for a `provider "aws" { ... }` block, an argument present in
an override file completely replaces the corresponding argument in the
original block; an argument the override omits is inherited unchanged.
This is exactly the semantic tested here, on the real generated
artifact's real text — never a live plan.
"""

from __future__ import annotations

import re
from pathlib import Path

_GENERATED_MAIN_TF = Path("generated/req-20260926T215226Z/main.tf")
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


def test_generated_artifact_still_has_every_skip_flag_true_unmodified():
    """The real, committed artifact is untouched — proves this test
    reads the actual PR content, not a hypothetical."""
    args = _provider_aws_arguments(_GENERATED_MAIN_TF.read_text())
    for flag in _SKIP_FLAGS:
        assert args[flag] == "true"


def test_override_merge_result_has_every_skip_flag_false():
    """Simulates Terraform's own override-merge semantics: arguments
    present in the override completely replace the original's — this
    is the effective configuration Terraform would actually plan with,
    computed without ever invoking the terraform binary."""
    original = _provider_aws_arguments(_GENERATED_MAIN_TF.read_text())
    override = _provider_aws_arguments(_OVERRIDE_TEMPLATE.read_text())

    effective = {**original, **override}  # override wins per Terraform's own merge rule

    for flag in _SKIP_FLAGS:
        assert effective[flag] == "false", f"{flag} was not overridden"


def test_override_does_not_touch_any_non_provider_resource_in_the_generated_artifact():
    """The override only ever declares a provider "aws" block — it must
    never redeclare a resource/module/data block, which would make it
    generated infrastructure rather than execution-boundary config."""
    text = _OVERRIDE_TEMPLATE.read_text()
    assert not re.search(r'\b(resource|module|data)\s+"', text)

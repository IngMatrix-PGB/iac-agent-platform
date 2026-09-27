"""Batch 25, Task 4: the CI-owned Terraform provider override template
(design spec §0.1, human decision item 1). This is execution-boundary
configuration only — it must never be imported/referenced by anything
under `src/iac_agent/`, and it must explicitly re-enable AWS provider
authentication (Terraform's override-merge only replaces an argument
that is *explicitly present* in the override file — omitting an
argument does nothing, so the skip-flags must be explicitly set to
`false`, not left out)."""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATE_PATH = Path("ci/aws_plan/provider_override.tf.template")
_SRC_ROOT = Path("src/iac_agent")


def test_template_exists_and_declares_a_provider_aws_block():
    text = _TEMPLATE_PATH.read_text()
    assert re.search(r'provider\s+"aws"\s*\{', text)


def test_template_explicitly_disables_every_skip_flag():
    text = _TEMPLATE_PATH.read_text()
    for flag in (
        "skip_credentials_validation",
        "skip_requesting_account_id",
        "skip_metadata_api_check",
        "skip_region_validation",
    ):
        assert re.search(rf"{flag}\s*=\s*false", text), f"{flag} must be explicitly set to false"


def test_template_never_referenced_from_src():
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "ci/aws_plan" not in text
        assert "provider_override" not in text


def test_template_filename_will_be_recognized_as_a_terraform_override():
    # Terraform only merges override semantics for a file named exactly
    # "override.tf"/"override.tf.json" or ending in "_override.tf"/
    # "_override.tf.json" once materialized into a workspace — the
    # template itself is named descriptively, but the CI job (Task 13)
    # must materialize it as exactly override.tf or *_override.tf.
    assert _TEMPLATE_PATH.name.split(".template")[0].endswith(("override.tf",))

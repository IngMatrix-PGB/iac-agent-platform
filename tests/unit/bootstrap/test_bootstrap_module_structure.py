"""Batch 25, Task 2/8: structural proofs for the bootstrap Terraform
module (design spec §6). Text/regex-based, not an HCL parser — this
repo has no HCL-parsing dependency, and real compiler-level correctness
is proven separately, for real, by Task 10's `real_bootstrap_tool` test
against the actual `terraform` binary. This file only guards the things
a real `terraform validate` cannot: that no literal repository subject
is hardcoded, and that no unexpected resource type sneaks into this one
narrowly-scoped module."""

from __future__ import annotations

import re
from pathlib import Path

_BOOTSTRAP_ROOT = Path("bootstrap/aws-oidc")
_ALLOWED_RESOURCE_TYPES = {
    "aws_iam_openid_connect_provider",
    "aws_iam_role",
    "aws_iam_role_policy",
}


def _all_tf_text() -> str:
    return "\n".join(p.read_text() for p in sorted(_BOOTSTRAP_ROOT.glob("*.tf")))


def test_exactly_one_oidc_provider_and_one_role():
    text = _all_tf_text()
    assert len(re.findall(r'resource\s+"aws_iam_openid_connect_provider"', text)) == 1
    assert len(re.findall(r'resource\s+"aws_iam_role"\s', text)) == 1


def test_no_resource_type_outside_the_allowed_iam_bootstrap_set():
    text = _all_tf_text()
    found = set(re.findall(r'resource\s+"(aws_[a-z0-9_]+)"', text))
    unexpected = found - _ALLOWED_RESOURCE_TYPES
    assert not unexpected, f"unexpected resource types: {unexpected}"


def test_trust_policy_subject_is_a_variable_never_a_literal_repo_string():
    text = _all_tf_text()
    assert "IngMatrix-PGB/iac-agent-platform" not in text
    assert "var.github_oidc_subject" in text


def test_trust_policy_restricts_audience_to_sts_amazonaws_com():
    text = _all_tf_text()
    assert "sts.amazonaws.com" in text


def test_permissions_policy_is_loaded_from_the_frozen_json_document():
    text = _all_tf_text()
    assert "iac_plan_role_permissions.json" in text


def test_readme_states_never_applied_by_iac_agent_platform():
    readme = (_BOOTSTRAP_ROOT / "README.md").read_text().lower()
    assert "never applied by iac-agent-platform" in readme

"""Batch 24, Task 11: structural proof that `terraform apply` is
nowhere in this platform — the CLI package included."""

from __future__ import annotations

from pathlib import Path

from iac_agent.execution.terraform_runner import TerraformRunner


def test_terraform_runner_has_no_apply_or_destroy():
    assert not hasattr(TerraformRunner, "apply")
    assert not hasattr(TerraformRunner, "destroy")


def test_cli_package_source_has_no_apply_invocation():
    # The design spec (§7) *requires* the literal trailer
    # "terraform apply: not executed" on every report — an explicit
    # negation, not an invocation. It is carved out here so this check
    # still catches any other, genuine mention of an apply/destroy
    # command without permanently conflicting with its own mandated
    # trailer text.
    root = Path("src/iac_agent/cli")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        sanitized = text.replace("terraform apply: not executed", "")
        assert "terraform apply" not in sanitized
        assert "terraform destroy" not in sanitized

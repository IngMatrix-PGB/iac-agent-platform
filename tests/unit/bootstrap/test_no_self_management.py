"""Batch 25, Task 9 (Gate A closing task): the final structural proof
tying Tasks 1-8 together — iac-agent-platform never gains authority to
create/modify its own AWS trust boundary, and no apply/destroy
capability exists anywhere in the new bootstrap/CI surface either."""

from __future__ import annotations

from pathlib import Path

from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import _DEFAULT_TRUSTED_MODULE_DIRS

_SRC_ROOT = Path("src/iac_agent")
_NEW_SURFACE_DIRS = (Path("bootstrap"), Path("ci/aws_plan"))


def test_terraform_runner_still_has_no_apply_or_destroy():
    assert not hasattr(TerraformRunner, "apply")
    assert not hasattr(TerraformRunner, "destroy")


def test_bootstrap_and_ci_directories_absent_from_trusted_module_dirs():
    trusted_paths = {str(path) for path in _DEFAULT_TRUSTED_MODULE_DIRS.values()}
    for trusted_path in trusted_paths:
        assert "bootstrap" not in trusted_path
        assert "ci/aws_plan" not in trusted_path


def test_no_file_under_src_references_bootstrap_or_ci_aws_plan_by_path():
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "bootstrap/aws-oidc" not in text
        assert "bootstrap.aws_oidc" not in text
        assert "ci/aws_plan" not in text
        assert "ci.aws_plan" not in text


#: `.md` files are intentionally excluded: `bootstrap/aws-oidc/README.md`
#: legitimately documents the real `terraform apply` command a HUMAN
#: runs manually (design invariant 1) — that is the opposite of a code
#: invocation. This check instead covers every file type that could
#: actually be executed, templated into a workspace, or otherwise
#: influence a real run: Terraform source, the frozen policy document,
#: Python, and workflow YAML/templates.
_SCANNED_SUFFIXES = (".tf", ".json", ".py", ".yml", ".yaml", ".template")


def test_no_apply_or_destroy_invocation_in_any_executable_new_surface_file():
    for directory in _NEW_SURFACE_DIRS:
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            assert "terraform apply" not in text, f"{path} contains terraform apply"
            assert "terraform destroy" not in text, f"{path} contains terraform destroy"

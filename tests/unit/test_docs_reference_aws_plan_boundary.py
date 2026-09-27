"""Batch 25, Task 7: README references the new AWS plan boundary
operator runbook, mirroring the existing pattern for every other
docs/*.md file (e.g. docs/ci.md, docs/real-llm-intent-interpreter.md)."""

from __future__ import annotations

from pathlib import Path


def test_readme_references_aws_plan_boundary_doc():
    readme = Path("README.md").read_text()
    assert "docs/aws-plan-boundary.md" in readme


def test_aws_plan_boundary_doc_exists():
    assert Path("docs/aws-plan-boundary.md").exists()

"""Batch 25, Task 1: `real_aws_plan`/`real_bootstrap_tool` markers are
registered exactly like the existing `real_tool`/`real_llm` markers —
classification only, no default-collection behavior change."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_real_aws_plan_and_real_bootstrap_tool_markers_registered():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    markers_text = "\n".join(data["tool"]["pytest"]["ini_options"]["markers"])
    assert "real_aws_plan:" in markers_text
    assert "real_bootstrap_tool:" in markers_text

"""Report-only Classify job records shards without gating other jobs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_CI = Path(".github/workflows/ci.yml")

_OUTPUT_NAMES = (
    "s3",
    "sqs",
    "dynamodb",
    "ecr",
    "lambda",
    "api_gateway",
    "api_lambda",
    "api_lambda_dynamodb",
    "serverless_worker",
    "security",
    "bootstrap",
    "frontend",
    "full",
    "reasons",
)

_CLASSIFY_COMMAND = re.compile(r"python scripts/ci_classify\.py\b")


def _jobs() -> dict:
    loaded = yaml.safe_load(_CI.read_text())
    return loaded["jobs"]


def _text() -> str:
    return _CI.read_text()


def _classify_script() -> str:
    classify = _jobs()["classify"]
    return "\n".join(step.get("run", "") for step in classify["steps"])


def _classify_invocations(script: str) -> list[str]:
    lines = script.splitlines()
    invocations: list[str] = []
    index = 0
    while index < len(lines):
        if not _CLASSIFY_COMMAND.search(lines[index]):
            index += 1
            continue
        parts = [lines[index]]
        while parts[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            parts.append(lines[index])
        invocations.append(" ".join(part.replace("\\", " ") for part in parts))
        index += 1
    return invocations


def test_classify_job_always_runs_and_does_not_gate_others():
    jobs = _jobs()
    classify = jobs["classify"]
    assert classify["name"] == "Classify"
    assert classify["runs-on"] == "ubuntu-24.04"
    assert "if" not in classify
    assert "tool-validation" in jobs
    assert "if" not in jobs["tool-validation"]
    assert "if" not in jobs["quality"]
    assert "if" not in jobs["tests"]
    script = "\n".join(step.get("run", "") for step in classify["steps"])
    assert "scripts/ci_classify.py" in script
    assert "pytest -m real_tool" in _text()


def test_classify_outputs_include_reasons_and_every_shard():
    classify = _jobs()["classify"]
    outputs = classify["outputs"]
    assert list(outputs) == list(_OUTPUT_NAMES)
    for name in _OUTPUT_NAMES:
        assert outputs[name] == f"${{{{ steps.result.outputs.{name} }}}}"
    assert "needs" not in classify


def test_unreadable_invocation_passes_paths_file():
    invocations = _classify_invocations(_classify_script())
    unreadable = [invocation for invocation in invocations if "--unreadable" in invocation]
    assert unreadable
    for invocation in unreadable:
        assert "--paths-file" in invocation
        assert "--unreadable" in invocation


def test_unreadable_invocation_never_omits_paths_file():
    script = _classify_script()
    invocations = _classify_invocations(script)
    assert invocations
    assert not any(
        "--unreadable" in invocation and "--paths-file" not in invocation
        for invocation in invocations
    )
    assert "|| true" not in script


def test_workflow_has_no_paths_ignore():
    assert "paths-ignore" not in _text()


def test_classify_checkout_fetches_full_history():
    steps = _jobs()["classify"]["steps"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["fetch-depth"] == 0


def test_quality_tests_and_tool_validation_have_no_if():
    jobs = _jobs()
    for key in ("quality", "tests", "tool-validation", "frontend"):
        assert "if" not in jobs[key]

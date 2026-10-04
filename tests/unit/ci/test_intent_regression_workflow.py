"""Authority boundary for the dispatch-only live intent regression workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW = Path(".github/workflows/intent-regression.yml")
_CI = Path(".github/workflows/ci.yml")

_FORBIDDEN_TEXT = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "id-token",
    "pull_request",
    "schedule",
    "IaCPlanRole",
    "IAC_AGENT_OPERATOR_SECRET",
    "GITHUB_TOKEN",
)


def _trigger(workflow: dict):
    # PyYAML 1.1 parses the bare key `on` as boolean True.
    if "on" in workflow:
        return workflow["on"]
    return workflow[True]


def test_intent_regression_workflow_is_dispatch_only_and_read_only():
    text = _WORKFLOW.read_text()
    workflow = yaml.safe_load(text)
    assert set(_trigger(workflow)) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["live-intent-regression"]
    assert job["timeout-minutes"] == 35
    assert "id-token" not in workflow["permissions"]
    script = "\n".join(step.get("run", "") or "" for step in job["steps"])
    assert "python -m evals.live_intent_regression" in script
    assert "terraform" not in script
    for forbidden in _FORBIDDEN_TEXT:
        assert forbidden not in text
    env = next(step["env"] for step in job["steps"] if "env" in step)
    assert env["IAC_AGENT_LLM_PROVIDER"] == "openai"
    assert env["IAC_AGENT_LLM_MODEL"] == "gpt-5-nano"
    assert env["OPENAI_API_KEY"] == "${{ secrets.OPENAI_API_KEY }}"
    upload = next(
        step
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "artifacts/evals/layer2/layer2-diagnostic.json"
    assert upload["with"]["if-no-files-found"] == "error"


def test_build_ci_still_excludes_the_real_model():
    text = _CI.read_text()
    assert 'pytest -m "not real_tool and not real_llm and not docker"' in text
    assert "evals.live_intent_regression" not in text
    assert "OPENAI_API_KEY" not in text

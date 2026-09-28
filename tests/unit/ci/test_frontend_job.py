"""The operator UI has its own CI job and does not change the Python markers."""

from __future__ import annotations

from pathlib import Path

import yaml

_CI = Path(".github/workflows/ci.yml")


def test_frontend_job_installs_tests_and_builds():
    workflow = yaml.safe_load(_CI.read_text())
    jobs = workflow["jobs"]
    frontend = next(job for job in jobs.values() if job.get("name") == "Frontend")
    runs = []
    working_directories = []
    for step in frontend["steps"]:
        if "run" in step:
            runs.append(step["run"])
        if "working-directory" in step:
            working_directories.append(step["working-directory"])
    script = "\n".join(runs)
    assert "npm ci" in script
    assert "npm test" in script
    assert "npm run build" in script
    assert "ui" in working_directories or "cd ui" in script
    text = _CI.read_text()
    assert 'pytest -m "not real_tool and not real_llm and not docker"' in text
    assert "pytest -m real_tool" in text
    assert "docker push" not in text

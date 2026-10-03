from pathlib import Path

import yaml

_CI = Path(".github/workflows/ci.yml")


def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text())["jobs"]


def test_every_job_runs_on_ubuntu_24_04():
    for name, job in _jobs().items():
        assert job["runs-on"] == "ubuntu-24.04", name


def test_existing_action_majors_stay_put():
    text = _CI.read_text()
    assert "actions/checkout@v4" in text
    assert "actions/setup-python@v5" in text
    assert "actions/setup-node@v4" in text
    assert "hashicorp/setup-terraform@v3" in text
    assert "actions/checkout@v7" not in text
    assert "actions/setup-python@v6" not in text
    assert "hashicorp/setup-terraform@v4" not in text

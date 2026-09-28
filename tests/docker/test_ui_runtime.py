"""The packaged image serves the operator UI and keeps API routes as JSON."""

from __future__ import annotations

import json
import subprocess
import textwrap
import time

import pytest

IMAGE = "iac-agent-platform:batch31"
NAME = "iac-agent-batch31-ui"
SECRET_MARKERS = ("sk-", "ghp_", "github_pat_", "AKIA")
PLACEHOLDER_ENV = [
    "GITHUB_OWNER=test",
    "GITHUB_REPOSITORY=test",
    "GITHUB_COMMIT_AUTHOR_NAME=test",
    "GITHUB_COMMIT_AUTHOR_EMAIL=test@example.com",
    "GITHUB_TOKEN=test",
    "IAC_AGENT_LLM_PROVIDER=openai",
    "IAC_AGENT_LLM_MODEL=test",
    "OPENAI_API_KEY=test",
    "IAC_AGENT_OBSERVABILITY=off",
]

pytestmark = pytest.mark.docker


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True)


@pytest.fixture(scope="module")
def image() -> str:
    result = _run(["docker", "build", "-t", IMAGE, "."])
    assert result.returncode == 0, result.stdout + result.stderr
    return IMAGE


def test_final_image_has_no_node_runtime(image: str) -> None:
    identity = _run(["docker", "run", "--rm", "--entrypoint", "id", image, "-u"])
    assert identity.returncode == 0, identity.stderr
    assert identity.stdout.strip() == "10001"
    for command in ("node", "npm", "npx"):
        found = _run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "/bin/sh",
                image,
                "-c",
                f"command -v {command}",
            ]
        )
        assert found.returncode != 0, found.stdout
    index = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "test -f /opt/iac-agent/ui/index.html",
        ]
    )
    assert index.returncode == 0, index.stderr


def test_running_container_serves_html_and_json(image: str) -> None:
    _run(["docker", "rm", "-f", NAME])
    env = [item for pair in PLACEHOLDER_ENV for item in ("-e", pair)]
    started = _run(["docker", "run", "-d", "--name", NAME, "--network", "none", *env, image])
    script = textwrap.dedent(
        """
        import json
        import re
        import urllib.error
        import urllib.request
        from pathlib import Path

        def fetch(path):
            url = "http://127.0.0.1:8000" + path
            try:
                with urllib.request.urlopen(url) as response:
                    body = response.read().decode()
                    kind = response.headers.get("content-type", "")
                    return response.status, kind, body
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers.get("content-type", ""), exc.read().decode()

        html = Path("/opt/iac-agent/ui/index.html").read_text()
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        fetched = {}
        for path in assets:
            status, kind, body = fetch(path)
            fetched[path] = [status, kind, body[:80]]
        print(json.dumps({
            "root": fetch("/"),
            "deep": fetch("/requests/req-example"),
            "health": fetch("/health"),
            "ready": fetch("/ready"),
            "unknown": fetch("/api/v1/nonexistent"),
            "missing": fetch("/api/v1/requests/req-missing"),
            "assets": fetched,
        }))
        """
    )
    try:
        assert started.returncode == 0, started.stderr
        deadline = time.monotonic() + 40
        ready = None
        while time.monotonic() < deadline:
            ready = _run(
                [
                    "docker",
                    "exec",
                    NAME,
                    "/opt/iac-agent/.venv/bin/python",
                    "-c",
                    "import urllib.request; print(urllib.request.urlopen("
                    "'http://127.0.0.1:8000/ready').read().decode())",
                ]
            )
            if ready.returncode == 0 and '"ready"' in ready.stdout:
                break
            time.sleep(1)
        logs = _run(["docker", "logs", NAME])
        assert ready is not None and ready.returncode == 0, logs.stdout + logs.stderr
        probed = _run(["docker", "exec", NAME, "/opt/iac-agent/.venv/bin/python", "-c", script])
        assert probed.returncode == 0, probed.stdout + probed.stderr + logs.stdout + logs.stderr
        report = json.loads(probed.stdout)
        root_status, root_type, root_body = report["root"]
        deep_status, deep_type, deep_body = report["deep"]
        assert root_status == 200
        assert "text/html" in root_type
        assert "IaC Agent Platform" in root_body
        assert deep_status == 200
        assert "text/html" in deep_type
        assert "IaC Agent Platform" in deep_body
        health_status, _health_type, health_body = report["health"]
        ready_status, _ready_type, ready_body = report["ready"]
        assert health_status == 200
        assert json.loads(health_body)["status"] == "ok"
        assert ready_status == 200
        assert json.loads(ready_body)["status"] == "ready"
        unknown_status, unknown_type, unknown_body = report["unknown"]
        assert unknown_status == 404
        assert "json" in unknown_type
        assert "<title>" not in unknown_body
        missing_status, missing_type, missing_body = report["missing"]
        assert missing_status == 404
        assert "json" in missing_type
        assert json.loads(missing_body)["error"] == "request_not_found"
        assert report["assets"], "index.html did not reference a built asset"
        for path, (status, content_type, _sample) in report["assets"].items():
            assert status == 200, path
            assert "text/html" not in content_type
    finally:
        _run(["docker", "rm", "-f", NAME])


def test_image_metadata_has_no_secret_markers(image: str) -> None:
    inspected = _run(["docker", "image", "inspect", image])
    history = _run(["docker", "history", "--no-trunc", image])
    assert inspected.returncode == 0, inspected.stderr
    assert history.returncode == 0, history.stderr
    blob = inspected.stdout + history.stdout
    for marker in SECRET_MARKERS:
        assert marker not in blob
    env = json.loads(inspected.stdout)[0]["Config"]["Env"]
    assert "IAC_AGENT_UI_DIST=/opt/iac-agent/ui" in env
    assert not any(item.startswith("OPENAI_API_KEY=") for item in env)
    assert not any(item.startswith("GITHUB_TOKEN=") for item in env)

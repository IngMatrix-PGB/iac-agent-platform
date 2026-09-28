"""Container replacement proof for the durable SQLite HITL boundary."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

IMAGE = "iac-agent-platform:batch30"
VOLUME = "iac-agent-gate-b-state"
CONTAINER_A = "iac-agent-gate-b-a"
CONTAINER_B = "iac-agent-gate-b-b"
REQUEST_ID = "req-docker-fresh"
PR_URL = "https://example.invalid/pull/7"
HARNESS = Path(__file__).resolve().parent / "harness.py"
DENIED = (
    "module.queue.aws_sqs_queue.this",
    "example-user",
    "example-bot@example.invalid",
    "iac-agent/req-docker-fresh",
    "base_branch",
    'resource "aws_sqs_queue"',
    "logical_name_hint",
    "arn:aws",
    "/var/lib/iac-agent/workspaces",
    "checkpoints",
)

pytestmark = pytest.mark.docker

_HTTP = r"""
import json, sys, urllib.error, urllib.request
method, path, raw = sys.argv[1], sys.argv[2], sys.argv[3]
data = raw.encode() if raw else None
headers = {"Content-Type": "application/json"} if data is not None else {}
request = urllib.request.Request(
    "http://127.0.0.1:8000" + path, data=data, method=method, headers=headers
)
try:
    with urllib.request.urlopen(request, timeout=300) as response:
        print(response.status)
        sys.stdout.write(response.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.code)
    sys.stdout.write(exc.read().decode())
"""


def _run(args: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True, timeout=timeout)


def _http(container: str, method: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    raw = "" if payload is None else json.dumps(payload)
    result = _run(
        [
            "docker",
            "exec",
            container,
            "/opt/iac-agent/.venv/bin/python",
            "-c",
            _HTTP,
            method,
            path,
            raw,
        ],
        timeout=360,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    status_text, _, body = result.stdout.partition("\n")
    return int(status_text), body


def _wait_until_ready(container: str) -> None:
    deadline = time.monotonic() + 60
    last = ""
    while time.monotonic() < deadline:
        result = _run(
            [
                "docker",
                "exec",
                container,
                "/opt/iac-agent/.venv/bin/python",
                "-c",
                _HTTP,
                "GET",
                "/health",
                "",
            ]
        )
        last = result.stdout + result.stderr
        if result.returncode == 0 and result.stdout.startswith("200"):
            return
        time.sleep(1)
    logs = _run(["docker", "logs", container])
    raise AssertionError(last + logs.stdout + logs.stderr)


def _start(name: str, volume: str, role: str) -> str:
    _run(["docker", "rm", "-f", name])
    started = _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "-v",
            f"{volume}:/var/lib/iac-agent/state",
            "-v",
            f"{HARNESS}:/tmp/harness.py:ro",
            "-e",
            f"IAC_AGENT_HARNESS_ROLE={role}",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            IMAGE,
            "/tmp/harness.py",
        ]
    )
    assert started.returncode == 0, started.stderr
    identity = _run(["docker", "inspect", "-f", "{{.Id}}", name])
    assert identity.returncode == 0, identity.stderr
    return identity.stdout.strip()


def _mounts(name: str) -> list[dict]:
    inspected = _run(["docker", "inspect", name])
    assert inspected.returncode == 0, inspected.stderr
    return json.loads(inspected.stdout)[0]["Mounts"]


def _assert_public(body: str) -> None:
    for needle in DENIED:
        assert needle not in body


def test_replacement_container_resumes_the_sqlite_checkpoint() -> None:
    _run(["docker", "rm", "-f", CONTAINER_A, CONTAINER_B])
    _run(["docker", "volume", "rm", "-f", VOLUME])
    created = _run(["docker", "volume", "create", VOLUME])
    assert created.returncode == 0, created.stderr
    try:
        id_a = _start(CONTAINER_A, VOLUME, "a")
        mounts = _mounts(CONTAINER_A)
        assert [item["Destination"] for item in mounts if item["Type"] == "volume"] == [
            "/var/lib/iac-agent/state"
        ]
        assert all(item["Destination"] != "/var/lib/iac-agent/workspaces" for item in mounts)
        _wait_until_ready(CONTAINER_A)
        status, body = _http(
            CONTAINER_A,
            "POST",
            "/api/v1/requests",
            {
                "natural_language_request": (
                    "build a worker that processes a queue and stores results"
                ),
                "request_id": REQUEST_ID,
            },
        )
        assert status == 201, body
        created_body = json.loads(body)
        assert created_body["outcome"] == "awaiting_approval"
        assert created_body["workflow"]["workflow_status"] == "awaiting_approval"
        _assert_public(body)

        threads = _run(
            [
                "docker",
                "exec",
                CONTAINER_A,
                "/opt/iac-agent/.venv/bin/python",
                "-c",
                "import os, sqlite3; "
                "connection = sqlite3.connect(os.environ['IAC_AGENT_STATE_DB']); "
                "print([row[0] for row in connection.execute("
                "'select distinct thread_id from checkpoints')])",
            ]
        )
        assert threads.returncode == 0, threads.stderr
        assert REQUEST_ID in threads.stdout

        calls_before = _run(
            [
                "docker",
                "exec",
                CONTAINER_A,
                "/opt/iac-agent/.venv/bin/python",
                "-c",
                "from pathlib import Path; "
                "path = Path('/var/lib/iac-agent/state/publisher-calls'); "
                "print(path.read_text() if path.exists() else '0')",
            ]
        )
        assert calls_before.stdout.strip() == "0"

        stopped = _run(["docker", "stop", CONTAINER_A], timeout=30)
        assert stopped.returncode == 0, stopped.stderr
        removed = _run(["docker", "rm", CONTAINER_A])
        assert removed.returncode == 0, removed.stderr
        gone = _run(["docker", "inspect", CONTAINER_A])
        assert gone.returncode != 0

        persisted = _run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "/bin/sh",
                "-v",
                f"{VOLUME}:/var/lib/iac-agent/state",
                IMAGE,
                "-c",
                "ls -1 /var/lib/iac-agent/state",
            ]
        )
        assert persisted.returncode == 0, persisted.stderr
        names = set(persisted.stdout.split())
        assert "state.db" in names
        assert names <= {"state.db", "state.db-wal", "state.db-shm", "publisher-calls"}

        id_b = _start(CONTAINER_B, VOLUME, "b")
        assert id_b != id_a
        _wait_until_ready(CONTAINER_B)
        missing_status, missing_body = _http(
            CONTAINER_B, "GET", "/api/v1/requests/req-missing"
        )
        assert missing_status == 404
        assert json.loads(missing_body) == {
            "error": "request_not_found",
            "message": "Request not found.",
        }
        assert "pending" not in missing_body

        loaded_status, loaded_body = _http(
            CONTAINER_B, "GET", f"/api/v1/requests/{REQUEST_ID}"
        )
        assert loaded_status == 200, loaded_body
        loaded = json.loads(loaded_body)
        assert loaded["outcome"] == "awaiting_approval"
        assert loaded["workflow"]["workflow_status"] == "awaiting_approval"
        _assert_public(loaded_body)

        approved_status, approved_body = _http(
            CONTAINER_B,
            "POST",
            f"/api/v1/requests/{REQUEST_ID}/approval",
            {"decision": "approve"},
        )
        assert approved_status == 200, approved_body
        approved = json.loads(approved_body)
        assert approved["outcome"] == "pr_created"
        assert approved["workflow"]["workflow_status"] == "pr_created"
        assert approved["workflow"]["pull_request"] == {"url": PR_URL}
        _assert_public(approved_body)

        calls_after = _run(
            [
                "docker",
                "exec",
                CONTAINER_B,
                "/opt/iac-agent/.venv/bin/python",
                "-c",
                "print(open('/var/lib/iac-agent/state/publisher-calls').read())",
            ]
        )
        assert calls_after.returncode == 0, calls_after.stderr
        assert calls_after.stdout.strip() == "1"
    finally:
        _run(["docker", "rm", "-f", CONTAINER_A, CONTAINER_B])
        _run(["docker", "volume", "rm", "-f", VOLUME])

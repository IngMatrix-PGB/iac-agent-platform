#!/usr/bin/env python3
"""One-off, explicitly-confirmed live GitHub smoke test (Batch 15).

Creates exactly ONE deterministic feature branch, ONE commit, and ONE
pull request against a real GitHub repository, through the real
Phase 1 application service (submit -> resume(APPROVE) -> PR_CREATED).

Hard safety rules enforced by THIS SCRIPT (not by `GitHubSourceControl`,
which stays generic and knows nothing about a specific repository):

  - refuses to run against any repository other than the one named
    below (checked, not merely configured)
  - refuses to run without --confirm-live-github
  - refuses to run without an explicit GITHUB_TOKEN (never a default)
  - never prints the token
  - performs read-only preflight checks before any mutation, and stops
    on the first failure without attempting to fix anything
  - creates at most one branch, one commit, and one pull request; never
    retries, never merges, never closes, never deletes

This is NOT a general deployment CLI — it exists only for this batch's
one controlled live verification. Do not extend it into a general
"create infra proposal" command; that belongs behind
`iac_agent.app.service.Phase1Application`, called from a future
FastAPI/CLI layer, not this script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from iac_agent.app.composition import open_application  # noqa: E402
from iac_agent.app.config import ApplicationConfig, load_github_token_from_env  # noqa: E402
from iac_agent.app.service import Phase1Application  # noqa: E402
from iac_agent.domain.approval import ApprovalDecision  # noqa: E402
from iac_agent.domain.source_control import derive_branch_name  # noqa: E402
from iac_agent.domain.workflow import WorkflowStatus  # noqa: E402
from iac_agent.providers.aws.sqs.contract import (  # noqa: E402
    DlqSpec,
    EncryptionSpec,
    SQSResourceSpec,
)

# This live-repository restriction is deliberately hardcoded ONLY here,
# never in production GitHubSourceControl (see docs/source-control.md).
_EXPECTED_OWNER = "IngMatrix-PGB"
_EXPECTED_REPOSITORY = "iac-agent-platform"
_EXPECTED_BASE_BRANCH = "main"
_EXPECTED_LOCAL_BRANCH = "feat/phase-1-sqs-vertical-slice"
_REQUEST_ID = "phase1-sqs-live-smoke"

_API_BASE = "https://api.github.com"
_API_VERSION = "2026-03-10"


class PreflightError(RuntimeError):
    """A read-only preflight check failed — no mutation is attempted."""


def _api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "iac-agent-platform-live-smoke",
    }


def _api_get(path: str, token: str) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{_API_BASE}{path}", headers=_api_headers(token), method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body.decode("utf-8")) if body else {}
        except ValueError:
            return exc.code, {}


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def preflight(token: str, branch_name: str) -> None:
    status, body = _api_get("/user", token)
    if status != 200:
        raise PreflightError(f"could not verify active GitHub identity (status {status})")
    print(f"[preflight] active GitHub identity: {body.get('login')}")

    status, body = _api_get(f"/repos/{_EXPECTED_OWNER}/{_EXPECTED_REPOSITORY}", token)
    if status != 200:
        raise PreflightError(f"target repository not found or inaccessible (status {status})")
    permissions = body.get("permissions", {})
    if not permissions.get("push"):
        raise PreflightError("authenticated identity does not have write (push) permission")
    print(f"[preflight] repository exists; push permission: {permissions.get('push')}")

    status, _ = _api_get(
        f"/repos/{_EXPECTED_OWNER}/{_EXPECTED_REPOSITORY}/git/ref/heads/{_EXPECTED_BASE_BRANCH}",
        token,
    )
    if status != 200:
        raise PreflightError(
            f"base branch {_EXPECTED_BASE_BRANCH!r} does not exist (status {status})"
        )
    print(f"[preflight] base branch {_EXPECTED_BASE_BRANCH!r} exists")

    status, _ = _api_get(
        f"/repos/{_EXPECTED_OWNER}/{_EXPECTED_REPOSITORY}/git/ref/heads/{branch_name}", token
    )
    if status == 200:
        raise PreflightError(f"target branch {branch_name!r} already exists remotely")
    if status != 404:
        raise PreflightError(f"unexpected status {status} checking target branch existence")
    print(f"[preflight] target branch {branch_name!r} does not exist yet")

    status, body = _api_get(
        f"/repos/{_EXPECTED_OWNER}/{_EXPECTED_REPOSITORY}/pulls"
        f"?head={_EXPECTED_OWNER}:{branch_name}&state=open",
        token,
    )
    if status != 200:
        raise PreflightError(f"could not check for existing PRs (status {status})")
    if body:
        raise PreflightError(f"an open PR already targets head branch {branch_name!r}")
    print("[preflight] no existing open PR uses the target branch")

    if _run_git("status", "--porcelain"):
        raise PreflightError("local working tree is not clean")
    print("[preflight] local working tree is clean")

    current_branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    if current_branch != _EXPECTED_LOCAL_BRANCH:
        raise PreflightError(
            f"expected local branch {_EXPECTED_LOCAL_BRANCH!r}, got {current_branch!r}"
        )
    print(f"[preflight] local branch is {current_branch!r} as expected")

    remote_url = _run_git("remote", "get-url", "origin")
    if "@" in remote_url.split("://", 1)[-1].split("/")[0]:
        raise PreflightError("remote URL appears to embed credentials")
    print(f"[preflight] remote URL has no embedded credentials: {remote_url}")

    local_config = _run_git("config", "--local", "--list")
    if "token" in local_config.lower() or "extraheader" in local_config.lower():
        raise PreflightError("local git config appears to reference a token")
    print("[preflight] local git config has no token references")

    print("[preflight] ALL CHECKS PASSED\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-live-github",
        action="store_true",
        required=True,
        help="Required explicit confirmation flag — refuses to run without it.",
    )
    args = parser.parse_args()
    if not args.confirm_live_github:
        print("refusing to run without --confirm-live-github", file=sys.stderr)
        return 2

    token_secret = load_github_token_from_env()
    token = token_secret.get_secret_value()

    branch_name = derive_branch_name(_REQUEST_ID)

    try:
        preflight(token, branch_name)
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 1

    config = ApplicationConfig(
        workspace_root=_REPO_ROOT / "artifacts",
        state_db_path=_REPO_ROOT / "artifacts" / "state.db",
        terraform_module_path=_REPO_ROOT / "terraform" / "modules" / "sqs",
        github_owner=_EXPECTED_OWNER,
        github_repository=_EXPECTED_REPOSITORY,
        github_base_branch=_EXPECTED_BASE_BRANCH,
    )

    # Belt-and-suspenders: even if config were somehow mis-supplied,
    # this script never targets a different repository.
    if config.github_owner != _EXPECTED_OWNER or config.github_repository != _EXPECTED_REPOSITORY:
        print("refusing: configured repository is not the authorized live target", file=sys.stderr)
        return 2

    spec = SQSResourceSpec(
        name="iac-agent-phase1-demo",
        fifo=False,
        environment="demo",
        encryption=EncryptionSpec(enabled=True),
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"ManagedBy": "iac-agent-platform", "Purpose": "phase1-live-smoke"},
    )

    with open_application(config, github_token=token_secret) as application:
        app = Phase1Application.from_application(application)

        print(f"submitting request_id={_REQUEST_ID!r} ...")
        submit_view = app.submit(request_id=_REQUEST_ID, spec=spec)
        stage_value = submit_view.current_stage.value if submit_view.current_stage else None
        print(f"submit() -> workflow_status={submit_view.workflow_status.value}")
        print(f"submit() -> current_stage={stage_value}")
        print(f"security_status={submit_view.security_status}")
        print(f"plan_summary={submit_view.plan_summary}")

        if submit_view.workflow_status is not WorkflowStatus.AWAITING_APPROVAL:
            print(
                "submit() did not reach AWAITING_APPROVAL — stopping before any mutation",
                file=sys.stderr,
            )
            if submit_view.error is not None:
                print(f"error: {submit_view.error}", file=sys.stderr)
            return 1

        print("\nresuming with APPROVE ...")
        resume_view = app.resume(_REQUEST_ID, ApprovalDecision.APPROVE)
        resume_stage_value = resume_view.current_stage.value if resume_view.current_stage else None
        print(f"resume() -> workflow_status={resume_view.workflow_status.value}")
        print(f"resume() -> current_stage={resume_stage_value}")

        if resume_view.workflow_status is not WorkflowStatus.PR_CREATED:
            print("resume() did not reach PR_CREATED", file=sys.stderr)
            if resume_view.error is not None:
                print(f"error: {resume_view.error}", file=sys.stderr)
            return 1

        pr = resume_view.pull_request
        print(
            f"\nPR created: number={pr.number} url={pr.url} "
            f"branch={pr.branch} base_branch={pr.base_branch}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

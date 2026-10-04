"""Command line for the V3 prepare, verify, and plan stages."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from iac_agent.aws_plan.acceptance import evaluate_environment
from iac_agent.aws_plan.binding import GitHubPullRequestReader
from iac_agent.aws_plan.evidence import write_evidence
from iac_agent.aws_plan.execution import ConfigurationError
from iac_agent.aws_plan.orchestrator import plan_validated, prepare, verify_handoff_command
from iac_agent.aws_plan.outcomes import exit_code

_MODULE_DIR = Path(__file__).resolve().parents[3] / "terraform" / "modules" / "sqs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m iac_agent.aws_plan")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--pr-number", type=int, required=True)
    prepare_parser.add_argument("--proposal-sha", required=True)
    prepare_parser.add_argument("--purpose", required=True, choices=["profile", "acceptance"])
    prepare_parser.add_argument("--executor-sha", required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare_parser.add_argument("--evidence", type=Path)
    prepare_parser.add_argument("--module-dir", type=Path, default=_MODULE_DIR)

    verify_parser = sub.add_parser("verify-handoff")
    verify_parser.add_argument("--handoff", type=Path, required=True)
    verify_parser.add_argument("--executor-sha", required=True)
    verify_parser.add_argument("--evidence", type=Path, required=True)
    verify_parser.add_argument("--purpose", required=True, choices=["profile", "acceptance"])
    verify_parser.add_argument("--module-dir", type=Path, default=_MODULE_DIR)

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--handoff", type=Path, required=True)
    plan_parser.add_argument("--executor-sha", required=True)
    plan_parser.add_argument("--evidence", type=Path, required=True)
    plan_parser.add_argument("--purpose", required=True, choices=["profile", "acceptance"])
    plan_parser.add_argument("--module-dir", type=Path, default=_MODULE_DIR)

    check_parser = sub.add_parser("check-environment")
    check_parser.add_argument("--payload", type=Path, required=True)

    args = parser.parse_args(argv)
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if args.command == "check-environment":
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
        result = evaluate_environment(payload)
        print(result)
        return 0 if result == "ready" else 1
    if args.command == "prepare":
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            return exit_code_configuration()
        evidence = prepare(
            pr_number=args.pr_number,
            proposal_sha=args.proposal_sha,
            purpose=args.purpose,
            executor_sha=args.executor_sha,
            output_dir=args.output_dir,
            reader=GitHubPullRequestReader(token=token),
            show_blob=lambda sha, path: _git_show(args.repo_root, sha, path),
            module_source_dir=args.module_dir,
            workflow_run_id=run_id,
            workflow_run_attempt=run_attempt,
        )
        if evidence is None:
            return 0
        if args.evidence is not None:
            write_evidence(args.evidence, evidence)
        return exit_code(evidence.terminal_outcome)
    if args.command == "verify-handoff":
        return verify_handoff_command(
            handoff=args.handoff,
            executor_sha=args.executor_sha,
            evidence_path=args.evidence,
            purpose=args.purpose,
            module_source_dir=args.module_dir,
            workflow_run_id=run_id,
            workflow_run_attempt=run_attempt,
        )
    evidence = plan_validated(
        handoff_dir=args.handoff,
        executor_sha=args.executor_sha,
        module_source_dir=args.module_dir,
        evidence_path=args.evidence,
        purpose=args.purpose,
        load_credentials=lambda: os.environ,
        identity_lookup=_caller_identity,
        workflow_run_id=run_id,
        workflow_run_attempt=run_attempt,
    )
    return exit_code(evidence.terminal_outcome)


def exit_code_configuration() -> int:
    from iac_agent.aws_plan.outcomes import TerminalOutcome

    return exit_code(TerminalOutcome.CONFIGURATION_ERROR)


def _git_show(repo_root: Path, sha: str, path: str) -> str:
    fetch = subprocess.run(
        ["git", "fetch", "--depth=1", "origin", sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode != 0:
        raise ConfigurationError("proposal blob could not be fetched")
    shown = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        raise ConfigurationError("proposal blob could not be read")
    return shown.stdout


def _caller_identity() -> tuple[str, str]:
    completed = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("caller identity could not be read")
    try:
        payload = json.loads(completed.stdout)
        return str(payload["Account"]), str(payload["Arn"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("caller identity could not be read") from exc


if __name__ == "__main__":
    sys.exit(main())

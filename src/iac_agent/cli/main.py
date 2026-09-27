"""CLI orchestration: parse -> services -> present (design spec §6-§9).

Only this module wires parsing to `IntentResolutionService`/
`IacApplication`; it never constructs LangGraph `Command` objects
itself, never talks to Terraform/Checkov/GitHub directly, and every
business decision (resolve, submit, resume) is delegated to the
already-owned services on `holder`."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from typing import TextIO

from iac_agent.app.composition import (
    IntentApplication,
    create_intent_interpreter,
    open_intent_application,
)
from iac_agent.app.config import (
    MissingConfigurationError,
    load_application_config_from_env,
    load_github_token_from_env,
    load_intent_interpreter_config_from_env,
    load_openai_api_key_from_env,
)
from iac_agent.cli.approval import parse_cli_approval
from iac_agent.cli.ids import generate_request_id
from iac_agent.cli.parser import parse_args
from iac_agent.cli.present import render_interpreter_error, render_submission, render_workflow
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStatus
from iac_agent.intent.port import IntentInterpreterError

_EXIT_OK = 0
_EXIT_GENERAL_ERROR = 1
_EXIT_CLARIFICATION = 3
_EXIT_UNSUPPORTED = 4
_EXIT_BLOCKED = 5


def main(
    argv: list[str] | None = None,
    *,
    holder: IntentApplication | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    isatty: bool | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    is_tty = isatty if isatty is not None else stdin.isatty()

    args = parse_args(argv)

    if holder is not None:
        return _dispatch(
            args,
            holder=holder,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            isatty=is_tty,
            clock=clock,
        )

    try:
        config = load_application_config_from_env()
        github_token = load_github_token_from_env()
        interpreter = create_intent_interpreter(
            load_intent_interpreter_config_from_env(), api_key=load_openai_api_key_from_env()
        )
    except MissingConfigurationError as exc:
        stderr.write(str(exc) + "\n")
        return _EXIT_GENERAL_ERROR

    with open_intent_application(
        config, github_token=github_token, interpreter=interpreter
    ) as opened:
        return _dispatch(
            args,
            holder=opened,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            isatty=is_tty,
            clock=clock,
        )


def _dispatch(
    args,
    *,
    holder: IntentApplication,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    isatty: bool,
    clock: Callable[[], datetime] | None,
) -> int:
    if args.command == "propose":
        return _run_propose(
            args,
            holder=holder,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            isatty=isatty,
            clock=clock,
        )
    return _run_resume(args, holder=holder, stdout=stdout)


def _run_propose(
    args,
    *,
    holder: IntentApplication,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    isatty: bool,
    clock: Callable[[], datetime] | None,
) -> int:
    request_id = args.request_id
    if request_id is None:
        now = clock() if clock is not None else None
        request_id = generate_request_id(now=now)

    try:
        result = holder.intent_service.submit(
            request_id=request_id, natural_language_request=args.natural_language_request
        )
    except IntentInterpreterError as exc:
        stdout.write(render_interpreter_error(request_id=request_id, exc=exc) + "\n")
        return _EXIT_GENERAL_ERROR

    if result.approval_available and isatty:
        stdout.write(render_submission(result) + "\n")
        stderr.write("Approve? [y/N] ")
        decision = parse_cli_approval(stdin.readline())
        view = holder.application.resume(request_id, decision)
        stdout.write(render_workflow(view) + "\n")
        return _EXIT_GENERAL_ERROR if view.workflow_status is WorkflowStatus.ERROR else _EXIT_OK

    if result.approval_available:
        stdout.write(render_submission(result, include_resume_hint=True) + "\n")
        return _EXIT_OK

    stdout.write(render_submission(result) + "\n")
    return _exit_code_for_terminal_result(result)


def _run_resume(args, *, holder: IntentApplication, stdout: TextIO) -> int:
    view = holder.application.get_state(args.request_id)
    if view.workflow_status is not WorkflowStatus.AWAITING_APPROVAL:
        stdout.write(render_workflow(view) + "\n")
        if view.workflow_status is WorkflowStatus.BLOCKED:
            return _EXIT_BLOCKED
        return _EXIT_GENERAL_ERROR

    decision = ApprovalDecision.APPROVE if args.decision == "approve" else ApprovalDecision.REJECT
    view = holder.application.resume(args.request_id, decision)
    stdout.write(render_workflow(view) + "\n")
    return _EXIT_GENERAL_ERROR if view.workflow_status is WorkflowStatus.ERROR else _EXIT_OK


def _exit_code_for_terminal_result(result) -> int:
    outcome = result.resolution.outcome
    if outcome == "clarification_required":
        return _EXIT_CLARIFICATION
    if outcome == "unsupported":
        return _EXIT_UNSUPPORTED
    # outcome == "resolved" and not approval_available: BLOCKED or ERROR.
    assert result.workflow_view is not None
    if result.workflow_view.workflow_status is WorkflowStatus.BLOCKED:
        return _EXIT_BLOCKED
    return _EXIT_GENERAL_ERROR

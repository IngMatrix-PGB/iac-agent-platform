"""Batch 24, Task 4: argparse-only CLI parser — no I/O, no services."""

from __future__ import annotations

import pytest

from iac_agent.cli.parser import parse_args


def test_propose_positional_and_optional_request_id():
    ns = parse_args(["propose", "build a worker", "--request-id", "orders-demo"])
    assert ns.command == "propose"
    assert ns.natural_language_request == "build a worker"
    assert ns.request_id == "orders-demo"


def test_propose_without_request_id_leaves_none():
    ns = parse_args(["propose", "build a worker"])
    assert ns.request_id is None


def test_resume_approve():
    ns = parse_args(["resume", "orders-demo", "--approve"])
    assert ns.command == "resume"
    assert ns.request_id == "orders-demo"
    assert ns.decision == "approve"


def test_resume_reject():
    ns = parse_args(["resume", "orders-demo", "--reject"])
    assert ns.decision == "reject"


def test_resume_requires_exactly_one_decision():
    with pytest.raises(SystemExit) as exc:
        parse_args(["resume", "orders-demo"])
    assert exc.value.code == 2


def test_resume_rejects_both_flags():
    with pytest.raises(SystemExit) as exc:
        parse_args(["resume", "orders-demo", "--approve", "--reject"])
    assert exc.value.code == 2


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        parse_args(["deploy", "x"])
    assert exc.value.code == 2


def test_parser_has_no_dry_run_or_no_github():
    with pytest.raises(SystemExit):
        parse_args(["propose", "x", "--dry-run"])
    with pytest.raises(SystemExit):
        parse_args(["propose", "x", "--no-github"])

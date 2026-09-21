"""Argparse-only CLI parser (Batch 24, design spec §6.1).

No I/O, no service imports, no business logic — this module only
defines the two frozen commands (`propose` / `resume`) and their
arguments. stdlib `argparse` only; no Typer, Click, or Rich."""

from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="iac-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser("propose")
    propose.add_argument("natural_language_request")
    propose.add_argument("--request-id", default=None)

    resume = subparsers.add_parser("resume")
    resume.add_argument("request_id")
    decision_group = resume.add_mutually_exclusive_group(required=True)
    decision_group.add_argument("--approve", action="store_true")
    decision_group.add_argument("--reject", action="store_true")

    ns = parser.parse_args(argv)
    if ns.command == "resume":
        ns.decision = "approve" if ns.approve else "reject"
    return ns

"""Offline check for the GitHub Environment a human configures later."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_environment(payload: Mapping[str, Any] | None) -> str:
    """Return ``ready`` only when the normalized environment description is complete.

    ``custom_branch_policies`` must be the branch list ``["main"]``.
    The boolean flag returned by the GitHub environment object is not
    that list, and a workflow ``environment:`` key is not this payload.
    """
    if not isinstance(payload, Mapping) or payload.get("name") != "aws-plan":
        return "blocked"
    policy = payload.get("deployment_branch_policy")
    if not isinstance(policy, Mapping):
        return "blocked"
    if policy.get("custom_branch_policies") != ["main"]:
        return "blocked"
    rules = payload.get("protection_rules")
    if not isinstance(rules, list):
        return "blocked"
    for rule in rules:
        if not isinstance(rule, Mapping) or rule.get("type") != "required_reviewers":
            continue
        if "reviewers" in rule and not rule["reviewers"]:
            return "blocked"
        return "ready"
    return "blocked"

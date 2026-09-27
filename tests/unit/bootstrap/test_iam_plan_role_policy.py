"""Batch 25, Task 3/15: the frozen `IaCPlanRole` permissions document
starts at the empirical minimum (`sts:GetCallerIdentity` only, design
spec §0.2/§7/§8) and must never silently widen to a forbidden action."""

from __future__ import annotations

import json
from pathlib import Path

_POLICY_PATH = Path("bootstrap/aws-oidc/policy/iac_plan_role_permissions.json")

_FORBIDDEN_ACTION_PREFIXES = ("Create", "Update", "Delete", "Put", "Attach", "Detach", "Modify")
_FORBIDDEN_ACTIONS = {"iam:PassRole", "sts:AssumeRole"}


def _load_statements() -> list[dict]:
    policy = json.loads(_POLICY_PATH.read_text())
    return policy["Statement"]


def test_policy_starts_with_only_sts_get_caller_identity():
    statements = _load_statements()
    all_actions: set[str] = set()
    for statement in statements:
        actions = statement["Action"]
        all_actions.update([actions] if isinstance(actions, str) else actions)
    assert all_actions == {"sts:GetCallerIdentity"}


def test_no_forbidden_action_prefix_anywhere_in_the_policy():
    statements = _load_statements()
    for statement in statements:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            _service, _, verb = action.partition(":")
            assert not verb[0:1].isupper() or not any(
                verb.startswith(prefix) for prefix in _FORBIDDEN_ACTION_PREFIXES
            ), f"forbidden mutating action present: {action}"


def test_forbidden_named_actions_absent():
    statements = _load_statements()
    all_actions: set[str] = set()
    for statement in statements:
        actions = statement["Action"]
        all_actions.update([actions] if isinstance(actions, str) else actions)
    assert all_actions.isdisjoint(_FORBIDDEN_ACTIONS)


def test_every_statement_is_allow_only():
    statements = _load_statements()
    for statement in statements:
        assert statement["Effect"] == "Allow"

"""Deterministic analyzer for decoded `terraform show -json` output.

`analyze_plan` is a pure function: no subprocess, no filesystem, no
network, no AWS SDK, no Terraform CLI, no Checkov, no LangGraph, no
LLM. The same plan JSON always produces the same `PlanSummary`. It
reports facts only — it never decides pass/fail/security policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange

#: Every action-set shape Terraform's plan JSON is known to produce.
#: Both orderings of a create+delete replacement map to REPLACE.
#: Anything not in this table fails closed (raises PlanAnalysisError)
#: rather than being silently treated as a no-op — Phase 1 must not
#: guess at the meaning of a Terraform/provider action Batch 6 has not
#: explicitly reviewed and modeled.
_ACTION_SET_TO_PLAN_ACTION: dict[frozenset[str], PlanAction] = {
    frozenset({"create"}): PlanAction.CREATE,
    frozenset({"update"}): PlanAction.UPDATE,
    frozenset({"delete"}): PlanAction.DELETE,
    frozenset({"create", "delete"}): PlanAction.REPLACE,
    frozenset({"no-op"}): PlanAction.NO_OP,
    frozenset({"read"}): PlanAction.READ,
}


class PlanAnalysisError(Exception):
    """Raised when plan JSON is structurally invalid or contains a
    resource-change action combination this analyzer does not recognize.

    Messages identify the structural problem (an index, an address, a
    field name) but never include full before/after values or the raw
    plan payload.
    """


def analyze_plan(plan_json: Mapping[str, Any]) -> PlanSummary:
    """Convert decoded `terraform show -json` output into a `PlanSummary`."""
    if "resource_changes" not in plan_json:
        raise PlanAnalysisError("plan JSON is missing required key 'resource_changes'")

    raw_changes = plan_json["resource_changes"]
    if not isinstance(raw_changes, list):
        raise PlanAnalysisError(
            f"'resource_changes' must be a list, got {type(raw_changes).__name__}"
        )

    resource_changes = sorted(
        (_parse_resource_change(index, entry) for index, entry in enumerate(raw_changes)),
        key=lambda rc: rc.address,
    )

    resources_to_add = tuple(
        rc.address for rc in resource_changes if rc.action is PlanAction.CREATE
    )
    resources_to_change = tuple(
        rc.address for rc in resource_changes if rc.action is PlanAction.UPDATE
    )
    resources_to_destroy = tuple(
        rc.address
        for rc in resource_changes
        if rc.action in (PlanAction.DELETE, PlanAction.REPLACE)
    )
    destructive_change_detected = any(rc.destructive for rc in resource_changes)

    return PlanSummary(
        resource_changes=tuple(resource_changes),
        resources_to_add=resources_to_add,
        resources_to_change=resources_to_change,
        resources_to_destroy=resources_to_destroy,
        destructive_change_detected=destructive_change_detected,
    )


def _parse_resource_change(index: int, entry: Any) -> ResourceChange:
    if not isinstance(entry, dict):
        raise PlanAnalysisError(
            f"resource_changes[{index}] must be an object, got {type(entry).__name__}"
        )

    if "address" not in entry:
        raise PlanAnalysisError(f"resource_changes[{index}] is missing required key 'address'")
    address = entry["address"]
    if not isinstance(address, str) or not address:
        raise PlanAnalysisError(f"resource_changes[{index}].address must be a non-empty string")

    if "change" not in entry:
        raise PlanAnalysisError(
            f"resource_changes[{index}] ({address}) is missing required key 'change'"
        )
    change = entry["change"]
    if not isinstance(change, dict):
        raise PlanAnalysisError(f"resource_changes[{index}] ({address}).change must be an object")

    if "actions" not in change:
        raise PlanAnalysisError(
            f"resource_changes[{index}] ({address}).change is missing required key 'actions'"
        )
    actions = change["actions"]
    if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
        raise PlanAnalysisError(
            f"resource_changes[{index}] ({address}).change.actions must be a list of strings"
        )
    actions_tuple = tuple(actions)

    action = _classify_actions(address, actions_tuple)

    changed_fields = _compute_changed_fields(
        action,
        before=change.get("before"),
        after=change.get("after"),
        after_unknown=change.get("after_unknown"),
    )

    return ResourceChange(
        address=address,
        actions=actions_tuple,
        action=action,
        replacement=(action is PlanAction.REPLACE),
        destructive=("delete" in actions_tuple),
        changed_fields=changed_fields,
    )


def _classify_actions(address: str, actions: tuple[str, ...]) -> PlanAction:
    key = frozenset(actions)
    try:
        return _ACTION_SET_TO_PLAN_ACTION[key]
    except KeyError:
        raise PlanAnalysisError(
            f"resource_changes ({address}) has an unrecognized action combination: "
            f"{sorted(actions)!r}"
        ) from None


def _compute_changed_fields(
    action: PlanAction,
    before: Any,
    after: Any,
    after_unknown: Any,
) -> tuple[str, ...]:
    """Top-level field *names* (never values) that differ between before
    and after, for actions where both genuinely exist to compare.

    Conservative by design: fields Terraform marks as not-yet-known in
    `after_unknown` are excluded rather than guessed at, and no
    changed-fields are reported at all for CREATE/DELETE/NO_OP/READ,
    where a meaningful before/after comparison does not apply.
    """
    if action not in (PlanAction.UPDATE, PlanAction.REPLACE):
        return ()
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ()

    unknown_keys = set(after_unknown) if isinstance(after_unknown, dict) else set()
    changed = sorted(
        key for key in after if key not in unknown_keys and before.get(key) != after.get(key)
    )
    return tuple(changed)

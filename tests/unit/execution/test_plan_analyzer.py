"""Unit tests for the deterministic Terraform plan analyzer.

All plan JSON here is synthetic/hand-built — no subprocess or real
Terraform binary is involved. Real Terraform plan JSON is exercised
separately by tests/integration/test_plan_analyzer_integration.py.
"""

from __future__ import annotations

import pytest

from iac_agent.domain.plan import PlanAction, PlanSummary
from iac_agent.execution.plan_analyzer import PlanAnalysisError, analyze_plan


def _change(address, actions, before=None, after=None, after_unknown=None):
    change: dict = {"actions": actions, "before": before, "after": after}
    if after_unknown is not None:
        change["after_unknown"] = after_unknown
    return {"address": address, "change": change}


def _plan(resource_changes):
    return {"resource_changes": resource_changes}


# ---------------------------------------------------------------------------
# 1-9: one entry per action shape
# ---------------------------------------------------------------------------


def test_empty_resource_changes_produces_empty_summary():
    summary = analyze_plan(_plan([]))

    assert summary.resource_changes == ()
    assert summary.resources_to_add == ()
    assert summary.resources_to_change == ()
    assert summary.resources_to_destroy == ()
    assert summary.destructive_change_detected is False


def test_one_create():
    summary = analyze_plan(_plan([_change("aws_sqs_queue.this", ["create"])]))

    assert summary.resource_changes[0].action is PlanAction.CREATE
    assert summary.resources_to_add == ("aws_sqs_queue.this",)


def test_one_update():
    summary = analyze_plan(
        _plan(
            [
                _change(
                    "aws_sqs_queue.this",
                    ["update"],
                    before={"delay_seconds": 0},
                    after={"delay_seconds": 15},
                )
            ]
        )
    )

    assert summary.resource_changes[0].action is PlanAction.UPDATE
    assert summary.resources_to_change == ("aws_sqs_queue.this",)


def test_one_delete():
    summary = analyze_plan(_plan([_change("aws_sqs_queue.old", ["delete"])]))

    assert summary.resource_changes[0].action is PlanAction.DELETE
    assert summary.resources_to_destroy == ("aws_sqs_queue.old",)


def test_delete_create_replacement():
    summary = analyze_plan(_plan([_change("aws_sqs_queue.this", ["delete", "create"])]))

    assert summary.resource_changes[0].action is PlanAction.REPLACE


def test_create_delete_replacement():
    summary = analyze_plan(_plan([_change("aws_sqs_queue.this", ["create", "delete"])]))

    assert summary.resource_changes[0].action is PlanAction.REPLACE


def test_no_op():
    summary = analyze_plan(_plan([_change("aws_sqs_queue.this", ["no-op"])]))

    assert summary.resource_changes[0].action is PlanAction.NO_OP


def test_read():
    summary = analyze_plan(_plan([_change("data.aws_caller_identity.current", ["read"])]))

    assert summary.resource_changes[0].action is PlanAction.READ


def test_mixed_create_update_delete_plan():
    summary = analyze_plan(
        _plan(
            [
                _change("aws_sqs_queue.new", ["create"]),
                _change("aws_sqs_queue.existing", ["update"]),
                _change("aws_sqs_queue.old", ["delete"]),
            ]
        )
    )

    assert summary.resources_to_add == ("aws_sqs_queue.new",)
    assert summary.resources_to_change == ("aws_sqs_queue.existing",)
    assert summary.resources_to_destroy == ("aws_sqs_queue.old",)


# ---------------------------------------------------------------------------
# 10-14: destructive semantics
# ---------------------------------------------------------------------------


def test_replacement_sets_destructive_true():
    rc = analyze_plan(_plan([_change("x", ["create", "delete"])])).resource_changes[0]
    assert rc.destructive is True
    assert rc.replacement is True


def test_delete_sets_destructive_true():
    rc = analyze_plan(_plan([_change("x", ["delete"])])).resource_changes[0]
    assert rc.destructive is True
    assert rc.replacement is False


def test_create_does_not_set_destructive():
    rc = analyze_plan(_plan([_change("x", ["create"])])).resource_changes[0]
    assert rc.destructive is False


def test_update_does_not_set_destructive():
    rc = analyze_plan(_plan([_change("x", ["update"])])).resource_changes[0]
    assert rc.destructive is False


def test_summary_destructive_flag_true_if_any_resource_is_destructive():
    summary = analyze_plan(
        _plan(
            [
                _change("aws_sqs_queue.a", ["create"]),
                _change("aws_sqs_queue.b", ["delete"]),
            ]
        )
    )
    assert summary.destructive_change_detected is True


def test_summary_destructive_flag_false_if_no_resource_is_destructive():
    summary = analyze_plan(
        _plan(
            [
                _change("aws_sqs_queue.a", ["create"]),
                _change("aws_sqs_queue.b", ["update"]),
                _change("aws_sqs_queue.c", ["no-op"]),
            ]
        )
    )
    assert summary.destructive_change_detected is False


# ---------------------------------------------------------------------------
# 15-17: address-collection semantics
# ---------------------------------------------------------------------------


def test_resources_to_add_semantics():
    summary = analyze_plan(
        _plan([_change("a", ["create"]), _change("b", ["update"]), _change("c", ["no-op"])])
    )
    assert summary.resources_to_add == ("a",)


def test_resources_to_change_semantics():
    summary = analyze_plan(
        _plan([_change("a", ["create"]), _change("b", ["update"]), _change("c", ["delete"])])
    )
    assert summary.resources_to_change == ("b",)


def test_resources_to_destroy_includes_replacement_not_plain_create():
    summary = analyze_plan(
        _plan(
            [
                _change("a", ["create"]),
                _change("b", ["delete"]),
                _change("c", ["create", "delete"]),
            ]
        )
    )
    assert set(summary.resources_to_destroy) == {"b", "c"}
    assert "c" not in summary.resources_to_add  # replacement is never double-counted as a create


# ---------------------------------------------------------------------------
# 18-19: ordering / determinism
# ---------------------------------------------------------------------------


def test_resource_changes_are_ordered_deterministically_by_address():
    summary = analyze_plan(
        _plan([_change("zzz", ["create"]), _change("aaa", ["create"]), _change("mmm", ["create"])])
    )
    assert [rc.address for rc in summary.resource_changes] == ["aaa", "mmm", "zzz"]


def test_equivalent_reordered_input_produces_equal_summary():
    a = _plan([_change("a", ["create"]), _change("b", ["update"])])
    b = _plan([_change("b", ["update"]), _change("a", ["create"])])

    assert analyze_plan(a) == analyze_plan(b)


# ---------------------------------------------------------------------------
# 20-28: malformed input handling
# ---------------------------------------------------------------------------


def test_missing_resource_changes_key_raises():
    with pytest.raises(PlanAnalysisError, match="resource_changes"):
        analyze_plan({})


@pytest.mark.parametrize("bad_value", ["not-a-list", {}, 42, None])
def test_wrong_resource_changes_type_raises(bad_value):
    with pytest.raises(PlanAnalysisError, match="must be a list"):
        analyze_plan({"resource_changes": bad_value})


def test_entry_missing_address_raises():
    with pytest.raises(PlanAnalysisError, match="address"):
        analyze_plan(_plan([{"change": {"actions": ["create"], "before": None, "after": {}}}]))


def test_entry_missing_change_raises():
    with pytest.raises(PlanAnalysisError, match="change"):
        analyze_plan(_plan([{"address": "x"}]))


def test_change_missing_actions_raises():
    with pytest.raises(PlanAnalysisError, match="actions"):
        analyze_plan(_plan([{"address": "x", "change": {"before": None, "after": {}}}]))


@pytest.mark.parametrize("bad_actions", ["create", 42, {"create": True}, [1, 2]])
def test_wrong_actions_type_raises(bad_actions):
    with pytest.raises(PlanAnalysisError, match="actions"):
        analyze_plan(_plan([{"address": "x", "change": {"actions": bad_actions}}]))


def test_empty_actions_list_raises():
    with pytest.raises(PlanAnalysisError, match="unrecognized action"):
        analyze_plan(_plan([_change("x", [])]))


def test_unknown_action_raises():
    with pytest.raises(PlanAnalysisError, match="unrecognized action"):
        analyze_plan(_plan([_change("x", ["future_action"])]))


@pytest.mark.parametrize("bad_entry", ["not-a-dict", 42, ["nested", "list"], None])
def test_malformed_entry_type_raises(bad_entry):
    with pytest.raises(PlanAnalysisError, match="must be an object"):
        analyze_plan(_plan([bad_entry]))


# ---------------------------------------------------------------------------
# 29-30: sensitive-value hygiene
# ---------------------------------------------------------------------------


def test_error_text_does_not_dump_entire_raw_plan():
    huge_secret_marker = "SENSITIVE_MARKER_SHOULD_NOT_LEAK"
    entry = {
        "address": "x",
        "change": {
            "actions": ["update"],
            "before": {"password": huge_secret_marker},
            "after": {"password": "different"},
        },
    }

    # Trigger a malformed-input error unrelated to the sensitive field
    # by corrupting the sibling entry, and confirm the marker from a
    # *valid* entry elsewhere in the same plan never appears in any
    # error raised while parsing a different, broken entry.
    with pytest.raises(PlanAnalysisError) as exc_info:
        analyze_plan(_plan([entry, {"address": "y"}]))

    assert huge_secret_marker not in str(exc_info.value)


def test_raw_before_after_values_are_not_retained_wholesale():
    summary = analyze_plan(
        _plan(
            [
                _change(
                    "aws_sqs_queue.this",
                    ["update"],
                    before={"delay_seconds": 0, "arn": "arn:aws:sqs:us-east-1:111111111111:q"},
                    after={"delay_seconds": 15, "arn": "arn:aws:sqs:us-east-1:111111111111:q"},
                )
            ]
        )
    )
    rc = summary.resource_changes[0]

    assert not hasattr(rc, "before")
    assert not hasattr(rc, "after")
    # Only the field NAME is retained, never the value.
    assert rc.changed_fields == ("delay_seconds",)
    assert "111111111111" not in repr(rc)
    assert "arn:aws:sqs" not in repr(rc)


# ---------------------------------------------------------------------------
# changed_fields behavior (supporting coverage beyond the required list)
# ---------------------------------------------------------------------------


def test_changed_fields_empty_for_create():
    rc = analyze_plan(_plan([_change("x", ["create"], after={"name": "q"})])).resource_changes[0]
    assert rc.changed_fields == ()


def test_changed_fields_empty_for_delete():
    rc = analyze_plan(_plan([_change("x", ["delete"], before={"name": "q"})])).resource_changes[0]
    assert rc.changed_fields == ()


def test_changed_fields_excludes_unknown_after_values():
    rc = analyze_plan(
        _plan(
            [
                _change(
                    "x",
                    ["update"],
                    before={"name": "old", "arn": "arn:aws:sqs:...:old"},
                    after={"name": "old", "arn": None},
                    after_unknown={"arn": True},
                )
            ]
        )
    ).resource_changes[0]
    # "arn" differs but is marked unknown, so it is conservatively excluded.
    assert rc.changed_fields == ()


def test_plan_summary_equality_and_type():
    summary = analyze_plan(_plan([_change("x", ["create"])]))
    assert isinstance(summary, PlanSummary)
    assert summary.add_count == 1
    assert summary.change_count == 0
    assert summary.destroy_count == 0

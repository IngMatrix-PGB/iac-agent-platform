"""UTC request-id generation with an injectable clock and entropy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from iac_agent.cli.ids import generate_request_id
from iac_agent.cli.parser import parse_args
from iac_agent.domain.source_control import derive_branch_name
from iac_agent.domain.workflow import validate_request_id
from iac_agent.graph.workflow import _resolve_request_workspace
from iac_agent.intent.naming import fallback_base_name
from iac_agent.persistence.checkpoints import workflow_config


def test_generate_request_id_uses_injected_clock_and_entropy():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    assert (
        generate_request_id(now=now, entropy=lambda: "a1b2c3d4e5f6")
        == "req-20260918T232211Z-a1b2c3d4e5f6"
    )


def test_same_second_with_different_entropy_does_not_collide():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    first = generate_request_id(now=now, entropy=lambda: "a1b2c3d4e5f6")
    second = generate_request_id(now=now, entropy=lambda: "ffffffffaaaa")
    assert first != second


def test_generated_id_is_branch_path_and_name_safe():
    value = generate_request_id(
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        entropy=lambda: "0123456789ab",
    )
    assert validate_request_id(value) == value
    assert derive_branch_name(value) == f"iac-agent/{value}"
    assert len(value) <= 40
    assert fallback_base_name(value) != fallback_base_name("req-20260102T030405Z-ffffffffffff")


def test_legacy_timestamp_id_still_validates_and_branches():
    legacy = "req-20260918T232211Z"
    assert validate_request_id(legacy) == legacy
    assert derive_branch_name(legacy) == "iac-agent/req-20260918T232211Z"


def test_same_second_ids_keep_distinct_workspaces_and_exact_thread_ids(tmp_path):
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    first = generate_request_id(now=now, entropy=lambda: "a1b2c3d4e5f6")
    second = generate_request_id(now=now, entropy=lambda: "ffffffffffff")
    assert _resolve_request_workspace(tmp_path, first) != _resolve_request_workspace(
        tmp_path, second
    )
    assert workflow_config(first)["configurable"]["thread_id"] == first
    legacy = "req-20260918T232211Z"
    assert workflow_config(legacy)["configurable"]["thread_id"] == legacy


def test_explicit_request_id_is_not_rewritten():
    supplied = "req-20260918T232211Z"
    ns = parse_args(["propose", "build a queue", "--request-id", supplied])
    assert ns.request_id == supplied


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        generate_request_id(now=datetime(2026, 9, 18, 23, 22, 11))


def test_entropy_must_be_twelve_lowercase_hex_digits():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    with pytest.raises(ValueError):
        generate_request_id(now=now, entropy=lambda: "not-hex")

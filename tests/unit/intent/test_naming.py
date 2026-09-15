"""Tests for the deterministic naming boundary (Batch 21, Task 3).

Three distinct stages, kept distinct (spec §12): a raw hint, a
deterministic normalized/fallback base name owned by this module, and
(elsewhere, Task 4) the target `ResourceSpec`'s own validators as the
real authoritative check. Nothing here reads `confidence`,
`assumptions`, `user_provided_hints`, or `unresolved_questions` — this
module never sees an `ArchitectureIntent` at all.
"""

from __future__ import annotations

import pytest

from iac_agent.intent.naming import (
    component_name,
    fallback_base_name,
    normalize_hint,
    resolve_base_name,
)


def test_normalize_hint_lowercases_and_hyphenates_whitespace():
    assert normalize_hint("Order Processor") == "order-processor"


def test_normalize_hint_strips_disallowed_characters():
    assert normalize_hint("Order! Processor#1") == "order-processor-1"


def test_normalize_hint_collapses_repeated_hyphens():
    assert normalize_hint("order   ---   processor") == "order-processor"


def test_normalize_hint_strips_leading_and_trailing_hyphens():
    assert normalize_hint("--order-processor--") == "order-processor"


def test_normalize_hint_truncates_to_budget():
    long_hint = "a" * 200
    result = normalize_hint(long_hint)
    assert result is not None
    assert len(result) == 40


def test_normalize_hint_returns_none_for_none_input():
    assert normalize_hint(None) is None


def test_normalize_hint_returns_none_when_nothing_survives_stripping():
    assert normalize_hint("🎉🎉🎉") is None


def test_fallback_base_name_is_deterministic_for_same_request_id():
    assert fallback_base_name("req-001") == fallback_base_name("req-001")


def test_fallback_base_name_differs_for_different_request_ids():
    assert fallback_base_name("req-001") != fallback_base_name("req-002")


def test_fallback_base_name_is_valid_lowercase_hyphen_slug():
    name = fallback_base_name("Req_001!!")
    assert name == name.lower()
    assert all(ch.isalnum() or ch == "-" for ch in name)
    assert name.startswith("req-")


def test_resolve_base_name_prefers_normalized_hint_when_present():
    assert (
        resolve_base_name(logical_name_hint="Order Processor", request_id="req-001")
        == "order-processor"
    )


def test_resolve_base_name_falls_back_when_hint_is_none():
    assert resolve_base_name(logical_name_hint=None, request_id="req-001") == fallback_base_name(
        "req-001"
    )


def test_resolve_base_name_falls_back_when_hint_normalizes_to_empty():
    assert resolve_base_name(
        logical_name_hint="🎉🎉🎉", request_id="req-001"
    ) == fallback_base_name("req-001")


def test_component_name_appends_suffix_with_hyphen():
    assert component_name("order-processor", "queue") == "order-processor-queue"


@pytest.mark.parametrize(
    ("target_max_length", "suffix"),
    [
        (63, ""),
        (64, ""),
        (64, "function"),
        (80, "queue"),
        (255, "table"),
        (128, "api"),
    ],
)
def test_component_name_stays_within_every_target_contracts_max_length(target_max_length, suffix):
    base = resolve_base_name(logical_name_hint="x" * 200, request_id="req-001")
    name = component_name(base, suffix) if suffix else base
    assert len(name) <= target_max_length

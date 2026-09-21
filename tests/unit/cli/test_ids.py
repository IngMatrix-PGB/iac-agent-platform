"""Batch 24, Task 5: UTC request-id generation with an injectable clock
(design spec §6.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from iac_agent.cli.ids import generate_request_id
from iac_agent.domain.source_control import derive_branch_name
from iac_agent.domain.workflow import validate_request_id


def test_generate_request_id_uses_injected_clock_not_wall_clock():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    assert generate_request_id(now=now) == "req-20260918T232211Z"


def test_generated_id_is_branch_and_path_safe():
    value = generate_request_id(now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert validate_request_id(value) == value
    assert derive_branch_name(value) == f"iac-agent/{value}"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        generate_request_id(now=datetime(2026, 9, 18, 23, 22, 11))

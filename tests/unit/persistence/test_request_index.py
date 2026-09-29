"""Unit tests for the application-owned request index.

No workflow, checkpoint blobs, or HTTP. The table stores request_id and
created_at only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from iac_agent.persistence.request_index import open_request_index


def _clock(*stamps: datetime):
    pending = iter(stamps)

    def clock() -> datetime:
        return next(pending)

    return clock


def test_schema_is_created_and_safe_to_open_twice(tmp_path):
    db = tmp_path / "state.db"
    with open_request_index(db) as index:
        index.record("req-1")
    with open_request_index(db) as index:
        rows = index.newest(20)
    assert len(rows) == 1
    assert rows[0][0] == "req-1"
    assert rows[0][1].endswith("Z")
    assert "T" in rows[0][1]

    connection = sqlite3.connect(db)
    try:
        columns = connection.execute("PRAGMA table_info(request_index)").fetchall()
        names = [row[1] for row in columns]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert names == ["request_id", "created_at"]
    assert "checkpoints" not in tables
    assert "writes" not in tables


def test_duplicate_record_keeps_the_first_created_at(tmp_path):
    db = tmp_path / "state.db"
    first = datetime(2026, 9, 29, 0, 0, 1, tzinfo=UTC)
    second = datetime(2026, 9, 29, 0, 0, 2, tzinfo=UTC)
    later = datetime(2026, 9, 29, 0, 0, 3, tzinfo=UTC)
    with open_request_index(db, clock=_clock(first, second, later)) as index:
        index.record("req-old")
        index.record("req-new")
        index.record("req-old")
        assert index.newest(1) == (("req-new", "2026-09-29T00:00:02.000000Z"),)
        assert index.newest(20) == (
            ("req-new", "2026-09-29T00:00:02.000000Z"),
            ("req-old", "2026-09-29T00:00:01.000000Z"),
        )


def test_equal_timestamps_order_request_id_descending(tmp_path):
    db = tmp_path / "state.db"
    stamp = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
    with open_request_index(db, clock=_clock(stamp, stamp)) as index:
        index.record("req-a")
        index.record("req-b")
        assert index.newest(20) == (
            ("req-b", "2026-09-29T01:00:00.000000Z"),
            ("req-a", "2026-09-29T01:00:00.000000Z"),
        )


def test_reopen_preserves_rows(tmp_path):
    db = tmp_path / "state.db"
    stamp = datetime(2026, 9, 29, 2, 0, tzinfo=UTC)
    with open_request_index(db, clock=_clock(stamp)) as index:
        index.record("req-kept")
    with open_request_index(db, clock=_clock(datetime(2026, 9, 30, tzinfo=UTC))) as index:
        index.record("req-kept")
        assert index.newest(20) == (("req-kept", "2026-09-29T02:00:00.000000Z"),)


def test_record_rejects_an_unsafe_request_id(tmp_path):
    db = tmp_path / "state.db"
    with open_request_index(db) as index:
        with pytest.raises(ValueError):
            index.record("../req")

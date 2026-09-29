"""Application-owned catalog of checkpointed request ids.

The LangGraph checkpoint tables remain the workflow authority. This table
stores ``request_id`` and ``created_at`` only, in the same ``state.db`` file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from iac_agent.domain.workflow import validate_request_id

_CREATE = """
CREATE TABLE IF NOT EXISTS request_index (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
)
"""
_INSERT = "INSERT OR IGNORE INTO request_index (request_id, created_at) VALUES (?, ?)"
_NEWEST = """
SELECT request_id, created_at
FROM request_index
ORDER BY created_at DESC, request_id DESC
LIMIT ?
"""


def _format_created_at(stamp: datetime) -> str:
    if stamp.tzinfo is None:
        raise ValueError("created_at clock must be timezone-aware")
    return stamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RequestIndex:
    """One connection to ``request_index``. The caller owns its lifetime."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection = connection
        self._clock = clock if clock is not None else (lambda: datetime.now(UTC))

    def record(self, request_id: str) -> None:
        """Insert the id once. A repeat keeps the original ``created_at``."""
        validate_request_id(request_id)
        created_at = _format_created_at(self._clock())
        self._connection.execute(_INSERT, (request_id, created_at))
        self._connection.commit()

    def newest(self, limit: int) -> tuple[tuple[str, str], ...]:
        """Return at most ``limit`` rows, newest ``created_at`` first."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        rows = self._connection.execute(_NEWEST, (limit,)).fetchall()
        return tuple((str(row[0]), str(row[1])) for row in rows)


@contextmanager
def open_request_index(
    db_path: Path,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Iterator[RequestIndex]:
    """Open ``request_index`` on ``db_path`` and close the connection on exit.

    This is a second connection to the application state file. It does not
    create or read LangGraph checkpoint tables.
    """
    if db_path.exists() and db_path.is_dir():
        raise ValueError(f"db_path must be a file path, not an existing directory: {db_path}")
    if not db_path.parent.exists():
        raise ValueError(f"parent directory of db_path does not exist: {db_path.parent}")
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(_CREATE)
        connection.commit()
        yield RequestIndex(connection, clock=clock)
    finally:
        connection.close()

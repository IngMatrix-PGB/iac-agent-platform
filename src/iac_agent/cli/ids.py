"""UTC request-id generation with an injectable clock (design spec
§6.2). Application APIs still require an explicit `request_id` —
generation is CLI-owned only."""

from __future__ import annotations

from datetime import datetime, timezone


def generate_request_id(now: datetime | None = None) -> str:
    stamp = datetime.now(timezone.utc) if now is None else now
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return stamp.astimezone(timezone.utc).strftime("req-%Y%m%dT%H%M%SZ")

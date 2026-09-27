"""UTC request-id generation with an injectable clock and entropy.

The CLI and the HTTP adapter may call `generate_request_id`.
`IacApplication` still requires an explicit request_id. Caller-supplied
ids are not passed through this function.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

_SUFFIX_LENGTH = 12
_HEX_DIGITS = frozenset("0123456789abcdef")


def generate_request_id(
    now: datetime | None = None,
    *,
    entropy: Callable[[], str] | None = None,
) -> str:
    stamp = datetime.now(UTC) if now is None else now
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    source = uuid.uuid4().hex if entropy is None else entropy()
    suffix = source[:_SUFFIX_LENGTH]
    if len(suffix) != _SUFFIX_LENGTH or any(char not in _HEX_DIGITS for char in suffix):
        raise ValueError("entropy must provide 12 lowercase hex digits")
    return stamp.astimezone(UTC).strftime("req-%Y%m%dT%H%M%SZ-") + suffix

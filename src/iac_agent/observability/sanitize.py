"""Rewrite secret-shaped strings that already sit on a telemetry model.

This is not the allowlist. A string that matches here means the
projection copied something it should not have.
"""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass, replace

_REDACTED = "[redacted]"
_PATTERNS = (
    re.compile(r"(?i)aws_secret_access_key|aws_access_key_id|aws_session_token|openai_api_key|github_token"),
    re.compile(r"sk-lf-[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"ghp_[A-Za-z0-9]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"BEGIN PRIVATE KEY"),
)


def sanitize_telemetry(event):
    if not is_dataclass(event) or isinstance(event, type):
        raise TypeError("sanitize_telemetry accepts a telemetry dataclass instance")
    updates = {item.name: _sanitize_value(getattr(event, item.name)) for item in fields(event)}
    return replace(event, **updates)


def _sanitize_value(value):
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return sanitize_telemetry(value)
    return value


def _scrub(text: str) -> str:
    for pattern in _PATTERNS:
        if pattern.search(text):
            return _REDACTED
    return text

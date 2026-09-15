"""Deterministic naming: hint -> candidate base name -> component name
(Batch 21, Task 3).

Three distinct stages (spec §12), kept distinct on purpose:

1. `logical_name_hint` — raw, unvalidated, bounded to 128 characters on
   `ArchitectureIntent` (`iac_agent.intent.models`).
2. This module — deterministic, meaning-preserving normalization (or a
   fully deterministic, request-id-derived fallback when no usable hint
   exists). Never a synonym substitution, never a middle-truncation.
3. The *existing* target `ResourceSpec`'s own field validators (owned by
   `iac_agent.intent.resolver`, not this module) — the real,
   authoritative check.

Nothing here reads an `ArchitectureIntent` or any of its
non-authoritative metadata fields — this module only ever sees a plain
`str | None` hint and a plain `str` request_id.
"""

from __future__ import annotations

import hashlib
import re

#: Chars, after normalization — safely under every target contract's max
#: name length even after the longest suffix ("-function", 9 chars) is
#: appended (strictest ceiling: Lambda's own 64-char max, 64 - 9 = 55 > 40).
_HINT_BUDGET = 40

_DISALLOWED_RUN_PATTERN = re.compile(r"[^a-z0-9]+")
_LEADING_TRAILING_HYPHENS_PATTERN = re.compile(r"^-+|-+$")


def normalize_hint(hint: str | None) -> str | None:
    """Lowercase, hyphenate, strip disallowed characters, collapse
    repeated hyphens, strip leading/trailing hyphens, truncate to the
    hint budget. Returns `None` (discard entirely, never a mangled
    fragment) for `None` input or when nothing survives stripping."""
    if hint is None:
        return None

    lowered = hint.lower()
    hyphenated = _DISALLOWED_RUN_PATTERN.sub("-", lowered)
    stripped = _LEADING_TRAILING_HYPHENS_PATTERN.sub("", hyphenated)
    truncated = stripped[:_HINT_BUDGET]
    truncated = _LEADING_TRAILING_HYPHENS_PATTERN.sub("", truncated)

    return truncated or None


def fallback_base_name(request_id: str) -> str:
    """A fully deterministic, code-owned name derived from `request_id`
    — the same request-identity source
    `iac_agent.graph.workflow._resolve_request_workspace` already uses.
    Never random; the same `request_id` always yields the same name."""
    normalized = normalize_hint(request_id)
    if normalized is not None:
        return f"req-{normalized}"
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:12]
    return f"req-{digest}"


def resolve_base_name(*, logical_name_hint: str | None, request_id: str) -> str:
    """The one candidate base name a resolver uses for a resolved
    architecture's top-level name (and, via `component_name`, its
    sub-resource names): the normalized hint when present and usable,
    otherwise the deterministic `request_id`-derived fallback."""
    normalized = normalize_hint(logical_name_hint)
    if normalized is not None:
        return normalized
    return fallback_base_name(request_id)


def component_name(base: str, suffix: str) -> str:
    """A deterministically derived sub-resource name for a composition
    (e.g. `component_name("order-processor", "queue")` ->
    `"order-processor-queue"`). The composition's own top-level name and
    a standalone `S3ResourceSpec.name` use `base` directly instead —
    never call this with an empty suffix."""
    return f"{base}-{suffix}"

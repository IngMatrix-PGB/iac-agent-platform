"""Shared KMS key identifier validation (Phase 2).

Loose, deterministic, offline pattern matching for the shapes AWS
actually issues (a key ARN, an alias ARN, a bare alias name, or a bare
key ID). No network lookup is ever performed against KMS. This is
genuinely shared, resource-agnostic logic — both SQS's and S3's
encryption contracts accept an optional customer-managed KMS key in
exactly the same shape, so this is the one place that shape is defined,
reused by both rather than duplicated.
"""

from __future__ import annotations

import re

_KMS_KEY_ARN = r"arn:aws:kms:[a-z0-9-]+:\d{12}:key/[0-9a-fA-F-]{36}"
_KMS_ALIAS_ARN = r"arn:aws:kms:[a-z0-9-]+:\d{12}:alias/[A-Za-z0-9/_-]+"
_KMS_ALIAS_NAME = r"alias/[A-Za-z0-9/_-]+"
_KMS_BARE_KEY_ID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_KMS_KEY_ID_PATTERN = re.compile(
    rf"^({_KMS_KEY_ARN}|{_KMS_ALIAS_ARN}|{_KMS_ALIAS_NAME}|{_KMS_BARE_KEY_ID})$"
)


def validate_kms_key_id(value: str) -> str:
    """Validate and normalize a caller-supplied KMS key identifier.

    Accepts a key ARN, an alias ARN, a bare `alias/...` name, or a bare
    key ID (UUID form). Raises `ValueError` for anything else. Never
    contacts AWS — this only checks shape, the same way SQS's own
    encryption contract always has.
    """
    candidate = value.strip()
    if not candidate or not _KMS_KEY_ID_PATTERN.match(candidate):
        raise ValueError(
            f"kms_key_id {value!r} is not a recognizable KMS key ARN, alias, or key ID"
        )
    return candidate

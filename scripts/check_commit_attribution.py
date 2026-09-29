#!/usr/bin/env python3
"""Reject attribution trailers in a commit message or pull request body.

Ordinary prose that mentions Claude is allowed. Trailer lines and the
Cursor/Claude footer are not. Install the companion hook for this clone
without changing global Git configuration:

    git config core.hooksPath .githooks
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TRAILER = re.compile(r"(?im)^[ \t]*(?:Co-Authored-By|Generated-By)[ \t]*:")
_MADE_WITH = re.compile(r"(?i)Made with[ \t]+(?:\[[ \t]*)?(?:Cursor|Claude)\b")
_ANTHROPIC_MAIL = re.compile(r"(?i)noreply@anthropic\.com")


def attribution_violations(text: str) -> list[str]:
    found: list[str] = []
    if _TRAILER.search(text):
        found.append("attribution trailer")
    if _MADE_WITH.search(text):
        found.append("Made with Cursor or Claude footer")
    if _ANTHROPIC_MAIL.search(text):
        found.append("Anthropic noreply address")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_commit_attribution.py MESSAGE_FILE", file=sys.stderr)
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8")
    violations = attribution_violations(text)
    if violations:
        print("rejected attribution metadata: " + ", ".join(violations), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

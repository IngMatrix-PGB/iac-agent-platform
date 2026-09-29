"""The attribution guard rejects trailers and accepts ordinary prose."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_CHECKER = Path("scripts/check_commit_attribution.py")


def _result(tmp_path: Path, text: str) -> subprocess.CompletedProcess[str]:
    message = tmp_path / "message.txt"
    message.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(_CHECKER), str(message)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_normal_commit_message_is_accepted(tmp_path: Path) -> None:
    result = _result(tmp_path, "feat: record the durable request index\n")
    assert result.returncode == 0


def test_prose_mentioning_claude_is_accepted(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        "docs: note that Claude is not a Git author of this repository\n",
    )
    assert result.returncode == 0


def test_claude_co_authored_by_trailer_is_rejected(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        "feat: add an index\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>\n",
    )
    assert result.returncode == 1


def test_generated_by_attribution_is_rejected(tmp_path: Path) -> None:
    result = _result(tmp_path, "feat: add an index\n\nGenerated-By: Cursor\n")
    assert result.returncode == 1


def test_made_with_cursor_footer_is_rejected(tmp_path: Path) -> None:
    result = _result(tmp_path, "feat: add an index\n\nMade with Cursor\n")
    assert result.returncode == 1


def test_made_with_cursor_pull_request_footer_is_rejected(tmp_path: Path) -> None:
    result = _result(
        tmp_path,
        "Summary of the change.\n\nMade with [Cursor](https://cursor.com)\n",
    )
    assert result.returncode == 1

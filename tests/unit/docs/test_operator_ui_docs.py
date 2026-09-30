"""Operator-facing documentation for the local UI."""

from __future__ import annotations

from pathlib import Path


def test_api_doc_describes_the_operator_ui():
    text = Path("docs/api.md").read_text()
    assert "npm run dev" in text
    assert "127.0.0.1:8000" in text
    assert "same-origin" in text
    assert "IAC_AGENT_UI_DIST" in text
    assert "/requests/{request_id}" in text
    assert (
        "0.0.0.0 inside the container is network binding, "
        "not authentication or authorization."
    ) in text
    assert "The operator UI does not add authentication." not in text
    assert "IAC_AGENT_OPERATOR_SECRET" in text
    assert "Authorization: Bearer" in text
    assert '"error": "unauthenticated"' in text
    assert '"message": "Authentication is required."' in text
    assert "before request lookup" in text
    assert "localStorage" in text
    assert "sessionStorage" in text
    assert "IndexedDB" in text
    assert "cookies" in text
    assert "reload" in text
    assert "in memory" in text
    assert "not RBAC" in text
    assert "approving actor is not persisted" in text
    assert "127.0.0.1:8000:8000" in text
    assert "The operator UI does not make this API safe for public Internet exposure." in text
    assert (
        "GET /health and GET /ready do not prove AWS, OpenAI, GitHub, "
        "Langfuse, or Terraform Registry connectivity."
    ) in text
    assert "Co-Authored-By" not in text
    assert "Made with Cursor" not in text


def test_roadmap_marks_batch_31_complete_without_auth():
    text = Path("docs/roadmap.md").read_text()
    assert "Batch 31 — operator UI (complete)" in text
    assert "Batch 34 — operator authentication (complete)" in text
    lowered = text.lower()
    assert "authentication" in lowered
    assert "public deployment" in lowered
    assert "not started" in lowered
    assert "rbac" in lowered
    assert "Co-Authored-By" not in text
    assert "Made with Cursor" not in text


def test_env_example_names_the_operator_secret_without_a_value():
    lines = Path(".env.example").read_text().splitlines()
    matches = [line for line in lines if line.startswith("IAC_AGENT_OPERATOR_SECRET=")]
    assert matches == ["IAC_AGENT_OPERATOR_SECRET="]
    assert "VITE_" not in "\n".join(lines)

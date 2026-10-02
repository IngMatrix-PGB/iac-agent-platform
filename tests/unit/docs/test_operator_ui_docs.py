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
    assert "capability_unavailable" in text
    assert "Intent interpretation is not configured." in text
    assert "Source-control publishing is not configured." in text
    assert (
        "/ready means the state plane is open, not that GitHub or OpenAI "
        "is configured or reachable."
    ) in text
    assert "List and detail do not require GitHub or OpenAI." in text
    assert "Reject does not require GitHub." in text
    assert "Approve requires the GitHub publication group." in text
    assert "Submit of a new request requires the interpreter group." in text
    assert "A partial group fails startup." in text
    assert "GITHUB_BASE_BRANCH=main alone does not configure publication." in text
    assert "Co-Authored-By" not in text
    assert "Made with Cursor" not in text


def test_readme_states_the_local_operator_boundary():
    text = Path("README.md").read_text()
    assert "docs/superpowers/" not in text
    assert "docs/roadmap.md" not in text
    assert "Terraform apply is not performed." in text
    lowered = text.lower()
    assert "operator secret" in lowered
    assert "not rbac" in lowered
    assert "public deployment" in lowered
    assert "not started" in lowered
    assert "rbac" in lowered
    assert "tls" in lowered
    assert "remote or public deployment" in lowered
    assert "Co-Authored-By" not in text
    assert "Made with Cursor" not in text
    api = Path("docs/api.md").read_text()
    assert "lifespan or startup decoupling are not started" not in api
    assert (
        "GitHub and OpenAI configuration are still required before the process serves."
        not in api
    )


def test_env_example_names_the_operator_secret_without_a_value():
    lines = Path(".env.example").read_text().splitlines()
    matches = [line for line in lines if line.startswith("IAC_AGENT_OPERATOR_SECRET=")]
    assert matches == ["IAC_AGENT_OPERATOR_SECRET="]
    text = "\n".join(lines)
    assert "VITE_" not in text
    assert "Empty or whitespace-only values leave that capability absent." in text
    assert (
        "GITHUB_BASE_BRANCH=main is the default and does not by itself configure publication."
        in text
    )
    assert "A mixture of set and omitted variables in either group fails startup." in text

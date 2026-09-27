"""The FastAPI distribution stays off the application core import path."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path("src/iac_agent")
_FORBIDDEN = (
    _ROOT / "app" / "service.py",
    _ROOT / "intent" / "service.py",
    _ROOT / "graph" / "workflow.py",
    _ROOT / "cli" / "main.py",
)


def _imports_fastapi(tree: ast.AST) -> list[ast.AST]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "fastapi" for alias in node.names):
                found.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "fastapi":
                found.append(node)
    return found


def test_core_modules_do_not_import_fastapi():
    for path in _FORBIDDEN:
        tree = ast.parse(path.read_text())
        assert _imports_fastapi(tree) == [], path.as_posix()
    domain = _ROOT / "domain"
    for path in domain.rglob("*.py"):
        tree = ast.parse(path.read_text())
        assert _imports_fastapi(tree) == [], path.as_posix()


def test_api_app_may_import_fastapi():
    tree = ast.parse((_ROOT / "api" / "app.py").read_text())
    assert _imports_fastapi(tree)

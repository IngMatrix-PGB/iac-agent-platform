"""The Langfuse distribution stays off the import path of the application core."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path("src/iac_agent")

_FORBIDDEN_MODULE_LEVEL = (
    _ROOT / "app" / "service.py",
    _ROOT / "intent" / "service.py",
    _ROOT / "graph" / "workflow.py",
    _ROOT / "cli" / "main.py",
    _ROOT / "observability" / "port.py",
    _ROOT / "observability" / "__init__.py",
    _ROOT / "observability" / "adapters" / "__init__.py",
)


def _imports_langfuse(tree: ast.AST) -> list[ast.AST]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "langfuse" for alias in node.names):
                found.append(node)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == "langfuse"
        ):
            found.append(node)
    return found


def _is_nested_in_function(tree: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is target:
                    return True
    return False


def test_core_modules_do_not_import_langfuse():
    for path in _FORBIDDEN_MODULE_LEVEL:
        tree = ast.parse(path.read_text())
        assert _imports_langfuse(tree) == [], path.as_posix()


def test_langfuse_sdk_import_is_inside_a_function():
    path = _ROOT / "observability" / "adapters" / "langfuse.py"
    tree = ast.parse(path.read_text())
    imports = _imports_langfuse(tree)
    assert imports, "the optional client constructor must import langfuse lazily"
    assert all(_is_nested_in_function(tree, node) for node in imports)


def test_importing_the_application_does_not_load_the_langfuse_distribution():
    import iac_agent.app.composition
    import iac_agent.app.service
    import iac_agent.graph.workflow
    import iac_agent.intent.service
    import iac_agent.observability

    assert iac_agent.observability.__doc__
    import importlib.util

    assert importlib.util.find_spec("langfuse") is None
    import sys

    assert "langfuse" not in sys.modules

"""Structural proofs that `iac_agent.intent` never imports the trusted
pipeline it must stay isolated from (Batch 21, Task 8, spec §11.3, §18).

These are confirmatory/regression tests over invariants Tasks 1-6
already established by construction — the expected result on first run
is PASS, not a RED failure. If one of these ever fails, it names a real
violation introduced somewhere in `iac_agent.intent`, not a signal to
weaken the test.

Each test reads the target module's own source text and asserts a
forbidden import substring is absent — the same "mechanically
checkable" philosophy as
`tests/unit/intent/test_non_authoritative_metadata.py`'s confidence-grep
proof, applied to import isolation instead of a read invariant.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from iac_agent.intent import models, naming, port, resolver, service


def _imported_module_names(module) -> set[str]:
    """The set of top-level dotted module names this module actually
    imports (`import a.b.c` and `from a.b.c import x` both contribute
    `"a.b.c"`) — parsed via `ast`, never a raw substring search, so a
    docstring or comment merely *mentioning* another module's name
    (e.g. "mirrors `iac_agent.git.port`'s shape") is never mistaken for
    a real import."""
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def _has_forbidden_import(imported: set[str], forbidden_prefix: str) -> bool:
    return any(
        name == forbidden_prefix or name.startswith(f"{forbidden_prefix}.") for name in imported
    )


def test_models_module_imports_only_stdlib_and_pydantic():
    imported = _imported_module_names(models)
    assert not any(name.startswith("iac_agent") for name in imported)


def test_resolver_module_never_imports_execution_security_or_git_packages():
    imported = _imported_module_names(resolver)
    for forbidden in ("iac_agent.execution", "iac_agent.security", "iac_agent.git"):
        assert not _has_forbidden_import(imported, forbidden)


def test_naming_module_never_imports_execution_security_or_git_packages():
    imported = _imported_module_names(naming)
    for forbidden in ("iac_agent.execution", "iac_agent.security", "iac_agent.git"):
        assert not _has_forbidden_import(imported, forbidden)


def test_port_module_never_imports_execution_security_or_git_packages():
    imported = _imported_module_names(port)
    for forbidden in ("iac_agent.execution", "iac_agent.security", "iac_agent.git"):
        assert not _has_forbidden_import(imported, forbidden)


def test_service_module_only_imports_the_sanctioned_application_entry_point():
    imported = _imported_module_names(service)
    assert _has_forbidden_import(imported, "iac_agent.app.service")
    forbidden_modules = (
        "iac_agent.graph",
        "iac_agent.execution",
        "iac_agent.security",
        "iac_agent.git",
    )
    for forbidden in forbidden_modules:
        assert not _has_forbidden_import(imported, forbidden)


@pytest.mark.parametrize("module", [models, resolver, naming, port, service])
def test_no_intent_module_imports_langgraph_directly(module):
    imported = _imported_module_names(module)
    assert not _has_forbidden_import(imported, "langgraph")

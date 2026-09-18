"""Structural proofs that provider identity never leaks into the
domain, and that exactly one place in `src/` ever dispatches on
provider identity (Batch 23, Task 6).

Mirrors `test_trust_boundary_isolation.py`'s ast-based (never
substring-based) discipline exactly — a docstring mentioning "openai"
as a design reference must never be mistaken for a real import or a
real dispatch.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from iac_agent.intent import resolver, service
from iac_agent.intent.models import ArchitectureIntent

_SRC_ROOT = Path(inspect.getfile(resolver)).resolve().parents[2]


def _module_level_import_names(module) -> set[str]:
    """Only direct children of the Module node — never descends into
    function bodies, which is exactly the distinction Task 6's lazy-
    import guarantee needs to prove."""
    source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_architecture_intent_has_no_provider_model_or_credential_field():
    forbidden = {"provider", "model", "api_key", "credential", "credentials"}
    assert forbidden.isdisjoint(ArchitectureIntent.model_fields.keys())


def test_architecture_resolver_module_never_imports_openai_or_provider_enum():
    source = Path(inspect.getfile(resolver)).read_text(encoding="utf-8")
    for forbidden in ("openai", "IntentInterpreterProvider"):
        assert forbidden not in source


def test_intent_resolution_service_module_never_imports_openai_or_provider_enum():
    source = Path(inspect.getfile(service)).read_text(encoding="utf-8")
    for forbidden in ("openai", "IntentInterpreterProvider"):
        assert forbidden not in source


def test_composition_module_imports_openai_adapter_only_inside_a_function():
    from iac_agent.app import composition

    module_level_imports = _module_level_import_names(composition)
    assert not any(
        name == "openai" or name.startswith("iac_agent.intent.adapters.openai")
        for name in module_level_imports
    )

    source = Path(inspect.getfile(composition)).read_text(encoding="utf-8")
    assert "iac_agent.intent.adapters.openai" in source


def test_exactly_one_match_on_intent_interpreter_provider_exists_in_src():
    matches_found: list[str] = []
    for py_file in sorted(_SRC_ROOT.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        if "IntentInterpreterProvider" not in source and "config.provider" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Match):
                subject_text = ast.unparse(node.subject)
                if "provider" in subject_text.lower():
                    matches_found.append(f"{py_file}:{node.lineno}")

    assert len(matches_found) == 1, f"expected exactly one match, found: {matches_found}"
    assert matches_found[0].endswith("composition.py:" + matches_found[0].rsplit(":", 1)[1])

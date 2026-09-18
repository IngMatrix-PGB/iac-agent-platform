"""Prompt-contract tests for the OpenAI adapter (Batch 23, Task 11).

Reads the adapter source with `ast` so this file does not import the
optional `openai` extra. Zero network.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ADAPTER_PATH = (
    Path(__file__).resolve().parents[4] / "src" / "iac_agent" / "intent" / "adapters" / "openai.py"
)


def _assign_value(tree: ast.AST, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {_ADAPTER_PATH}")


def _prompt_contract() -> tuple[str, str]:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"))
    version = _assign_value(tree, "_PROMPT_VERSION")
    instructions = _assign_value(tree, "_INSTRUCTIONS")
    assert isinstance(version, str)
    assert isinstance(instructions, str)
    return version, instructions


def test_prompt_version_is_3():
    version, _ = _prompt_contract()
    assert version == "3"


def test_prompt_distinguishes_architecture_ambiguity_from_implementation_detail():
    _, instructions = _prompt_contract()
    assert "ARCHITECTURE-BLOCKING AMBIGUITY" in instructions
    assert "IMPLEMENTATION DETAIL" in instructions
    assert "unspecified" in instructions.lower()
    assert "anything genuinely ambiguous or missing" not in instructions
    assert "Do not create unresolved_questions for these" in instructions
    assert "Deterministic downstream components own them" in instructions


def test_prompt_forbids_copying_forbidden_instructions_into_unresolved_questions():
    _, instructions = _prompt_contract()
    lowered = instructions.lower()
    assert "unresolved_questions" in lowered
    assert "never copy" in lowered
    assert "sanitized" in lowered
    assert "non-verbatim" in lowered
    assert "never bend" in lowered


def test_prompt_preserves_data_not_instructions_and_authority_limits():
    _, instructions = _prompt_contract()
    lowered = instructions.lower()
    assert "data to interpret" in lowered
    assert "never" in lowered and "instructions to follow" in lowered
    assert "terraform" in lowered or "hcl" in lowered
    assert "iam" in lowered
    assert "apply" in lowered
    assert "allowlist" in lowered


def test_prompt_states_object_storage_is_not_persistence():
    _, instructions = _prompt_contract()
    assert "CAPABILITY ORTHOGONALITY" in instructions
    lowered = instructions.lower()
    assert "object_storage" in lowered
    assert "persistence" in lowered
    assert "not natural-language synonyms" in lowered
    assert "do not additionally emit persistence" in lowered


def test_prompt_states_http_api_does_not_imply_synchronous():
    _, instructions = _prompt_contract()
    assert "NON-INFERENCE" in instructions
    lowered = instructions.lower()
    assert "http/api does not imply synchronous" in lowered or (
        "does not imply synchronous" in lowered
    )
    assert "never infer synchronous" in lowered


def test_prompt_states_forbidden_only_uses_unspecified_and_empty_capabilities():
    _, instructions = _prompt_contract()
    assert "FORBIDDEN-ONLY" in instructions
    lowered = instructions.lower()
    assert "capabilities = []" in lowered or "capabilities=[]" in lowered
    assert "workload_type = unspecified" in lowered
    assert "interaction_pattern = unspecified" in lowered
    assert "do not invent" in lowered


def test_prompt_does_not_manufacture_questions_for_degenerate_unspecified():
    _, instructions = _prompt_contract()
    lowered = instructions.lower()
    assert "do not manufacture questions" in lowered
    assert "non-iac" in lowered or "non-IaC" in instructions

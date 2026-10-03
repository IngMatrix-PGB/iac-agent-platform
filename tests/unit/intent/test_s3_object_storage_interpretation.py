"""The clear S3 object-storage sentence is a storage workload.

The OpenAI instructions own that classification. ArchitectureResolver
still requires workload_type=storage and does not infer it from
object_storage.
"""

from __future__ import annotations

import ast
from pathlib import Path

from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.resolver import (
    ArchitectureResolver,
    ClarificationReason,
    ClarificationRequired,
    ResolvedArchitecture,
)
from iac_agent.providers.aws.s3.contract import S3ResourceSpec

_ADAPTER = (
    Path(__file__).resolve().parents[3] / "src" / "iac_agent" / "intent" / "adapters" / "openai.py"
)
_S3_REQUEST = "Use S3 to store uploaded files."
_AMBIGUOUS_REQUEST = "I need something to process customer orders."


def _instructions() -> str:
    tree = ast.parse(_ADAPTER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_INSTRUCTIONS":
                    value = ast.literal_eval(node.value)
                    assert isinstance(value, str)
                    return value
    raise AssertionError("_INSTRUCTIONS not found")


def test_clear_s3_object_storage_sentence_resolves_to_the_trusted_s3_architecture():
    instructions = _instructions()
    assert _S3_REQUEST in instructions
    assert "workload_type=storage" in instructions
    assert "object_storage" in instructions
    assert (
        "Do not leave workload_type unspecified once object or blob storage is clear"
        in instructions
    )
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
        user_provided_hints=(AwsServiceHint.S3,),
    )
    result = ArchitectureResolver().resolve(intent=intent, request_id="req-s3-object-storage")
    assert isinstance(result, ResolvedArchitecture)
    assert isinstance(result.request_spec, S3ResourceSpec)
    assert result.matched_pattern == "storage+object_storage"


def test_ambiguous_request_remains_unspecified_and_requires_clarification():
    instructions = _instructions()
    assert _AMBIGUOUS_REQUEST in instructions
    assert "workload_type=unspecified" in instructions
    assert "Do not invent a workload for that request" in instructions
    intent = ArchitectureIntent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    result = ArchitectureResolver().resolve(intent=intent, request_id="req-ambiguous")
    assert isinstance(result, ClarificationRequired)
    assert result.request.reason is ClarificationReason.WORKLOAD_TYPE_REQUIRED

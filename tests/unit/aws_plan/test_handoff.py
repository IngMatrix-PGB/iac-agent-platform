"""Bounded handoff between V3 prepare and the credentialed plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from iac_agent.aws_plan.handoff import (
    HandoffRejected,
    verify_handoff,
    write_handoff,
)
from iac_agent.aws_plan.target import HANDOFF_MAX_BYTES, REPOSITORY_ID
from iac_agent.aws_plan.workspace import build_v3_workspace
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_MODULE = Path(__file__).resolve().parents[3] / "terraform" / "modules" / "sqs"
_EXECUTOR = "b" * 40
_PROPOSAL = "a" * 40


def _sample(tmp_path: Path) -> Path:
    spec = SQSResourceSpec(name="order-events")
    workspace = tmp_path / "built"
    build_v3_workspace(spec, module_source_dir=_MODULE, destination=workspace)
    root = tmp_path / "handoff"
    write_handoff(
        root,
        workspace=workspace,
        proposal_sha=_PROPOSAL,
        executor_sha=_EXECUTOR,
        pr_number=29,
        repository_id=REPOSITORY_ID,
        request_id="req-20261003T142705Z-913daf061bab",
        proposal_main_sha256="1" * 64,
        proposal_versions_sha256="2" * 64,
        spec=spec,
    )
    return root


def test_round_trip_verifies_hashes(tmp_path):
    root = _sample(tmp_path)
    manifest = verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)
    assert manifest.proposal_sha == _PROPOSAL
    assert manifest.executor_sha == _EXECUTOR
    assert manifest.pr_number == 29
    assert manifest.repository_id == REPOSITORY_ID
    assert manifest.request_id == "req-20261003T142705Z-913daf061bab"
    assert manifest.canonical_inputs.name == "order-events"
    assert manifest.proposal_main_sha256 == "1" * 64
    names = {item.path for item in manifest.files}
    assert "workspace/main.tf" in names
    assert "workspace/provider.tf" in names


def test_hash_mismatch_rejected(tmp_path):
    root = _sample(tmp_path)
    main_tf = root / "workspace" / "main.tf"
    main_tf.write_text(main_tf.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(HandoffRejected):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_extra_path_rejected(tmp_path):
    root = _sample(tmp_path)
    (root / "workspace" / "extra.tf").write_text("resource {}\n", encoding="utf-8")
    with pytest.raises(HandoffRejected):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_parent_segment_rejected(tmp_path):
    root = _sample(tmp_path)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"].append({"path": "workspace/../../secret", "size": 1, "sha256": "0" * 64})
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HandoffRejected, match="parent"):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_absolute_path_rejected(tmp_path):
    root = _sample(tmp_path)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"].append({"path": "/tmp/secret", "size": 1, "sha256": "0" * 64})
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HandoffRejected, match="absolute"):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_symlink_rejected(tmp_path):
    root = _sample(tmp_path)
    main_tf = root / "workspace" / "main.tf"
    main_tf.unlink()
    main_tf.symlink_to(root / "workspace" / "versions.tf")
    with pytest.raises(HandoffRejected, match="symlink"):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_over_one_mib_rejected(tmp_path):
    root = _sample(tmp_path)
    target = root / "workspace" / "modules" / "sqs" / "main.tf"
    blob = b"a" * (HANDOFF_MAX_BYTES + 1)
    target.write_bytes(blob)
    manifest_path = root / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(blob).hexdigest()
    for entry in payload["files"]:
        if entry["path"] == "workspace/modules/sqs/main.tf":
            entry["size"] = len(blob)
            entry["sha256"] = digest
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HandoffRejected, match="1 MiB"):
        verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)


def test_executor_sha_mismatch_rejected(tmp_path):
    root = _sample(tmp_path)
    with pytest.raises(HandoffRejected, match="executor") as raised:
        verify_handoff(root, expected_executor_sha="c" * 40, module_source_dir=_MODULE)
    assert raised.value.sha_mismatch is True


def test_job_b_rerender_matches_workspace(tmp_path):
    root = _sample(tmp_path)
    verify_handoff(root, expected_executor_sha=_EXECUTOR, module_source_dir=_MODULE)
    rebuilt = tmp_path / "rebuilt"
    spec = SQSResourceSpec(name="order-events")
    build_v3_workspace(spec, module_source_dir=_MODULE, destination=rebuilt)
    for path in rebuilt.rglob("*"):
        if path.is_file():
            relative = path.relative_to(rebuilt)
            assert (root / "workspace" / relative).read_bytes() == path.read_bytes()

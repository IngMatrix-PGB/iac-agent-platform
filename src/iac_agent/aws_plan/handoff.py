"""Manifest and hash checks for the Job A to Job B handoff."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from iac_agent.aws_plan.target import HANDOFF_MAX_BYTES
from iac_agent.aws_plan.workspace import build_v3_workspace
from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec

_ROOT_FILES = frozenset(
    {"workspace/main.tf", "workspace/versions.tf", "workspace/provider.tf"}
)
_MODULE_PREFIX = "workspace/modules/sqs/"


class HandoffRejected(ValueError):
    """The handoff artifact is not safe to plan."""

    def __init__(self, message: str, *, sha_mismatch: bool = False) -> None:
        super().__init__(message)
        self.sha_mismatch = sha_mismatch


@dataclass(frozen=True)
class CanonicalInputs:
    name: str
    fifo: bool
    visibility_timeout_seconds: int
    message_retention_seconds: int
    delay_seconds: int
    kms_key_id: str | None
    dlq_enabled: bool
    max_receive_count: int | None
    tags: dict[str, str]

    def to_spec(self) -> SQSResourceSpec:
        try:
            return SQSResourceSpec(
                name=self.name,
                fifo=self.fifo,
                visibility_timeout_seconds=self.visibility_timeout_seconds,
                message_retention_seconds=self.message_retention_seconds,
                delay_seconds=self.delay_seconds,
                encryption=EncryptionSpec(kms_key_id=self.kms_key_id),
                dlq=DlqSpec(
                    enabled=self.dlq_enabled,
                    max_receive_count=self.max_receive_count,
                ),
                tags=self.tags,
            )
        except ValidationError as exc:
            raise HandoffRejected("canonical inputs are not a valid SQSResourceSpec") from exc

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fifo": self.fifo,
            "visibility_timeout_seconds": self.visibility_timeout_seconds,
            "message_retention_seconds": self.message_retention_seconds,
            "delay_seconds": self.delay_seconds,
            "kms_key_id": self.kms_key_id,
            "dlq_enabled": self.dlq_enabled,
            "max_receive_count": self.max_receive_count,
            "tags": dict(sorted(self.tags.items())),
        }

    @classmethod
    def from_spec(cls, spec: SQSResourceSpec) -> CanonicalInputs:
        return cls(
            name=spec.name,
            fifo=spec.fifo,
            visibility_timeout_seconds=spec.visibility_timeout_seconds,
            message_retention_seconds=spec.message_retention_seconds,
            delay_seconds=spec.delay_seconds,
            kms_key_id=spec.encryption.kms_key_id,
            dlq_enabled=spec.dlq.enabled,
            max_receive_count=spec.dlq.max_receive_count,
            tags=dict(spec.tags),
        )

    @classmethod
    def from_json(cls, payload: object) -> CanonicalInputs:
        if not isinstance(payload, dict):
            raise HandoffRejected("canonical inputs are missing")
        try:
            tags = payload["tags"]
            if not isinstance(tags, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in tags.items()
            ):
                raise HandoffRejected("canonical tags are not a string map")
            return cls(
                name=payload["name"],
                fifo=payload["fifo"],
                visibility_timeout_seconds=payload["visibility_timeout_seconds"],
                message_retention_seconds=payload["message_retention_seconds"],
                delay_seconds=payload["delay_seconds"],
                kms_key_id=payload["kms_key_id"],
                dlq_enabled=payload["dlq_enabled"],
                max_receive_count=payload["max_receive_count"],
                tags=dict(tags),
            )
        except (KeyError, TypeError) as exc:
            raise HandoffRejected("canonical inputs are incomplete") from exc


@dataclass(frozen=True)
class HandoffFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class HandoffManifest:
    schema_version: str
    proposal_sha: str
    executor_sha: str
    pr_number: int
    repository_id: str
    request_id: str
    proposal_main_sha256: str
    proposal_versions_sha256: str
    canonical_inputs: CanonicalInputs
    files: tuple[HandoffFile, ...]


def write_handoff(
    root: Path,
    *,
    workspace: Path,
    proposal_sha: str,
    executor_sha: str,
    pr_number: int,
    repository_id: str,
    request_id: str,
    proposal_main_sha256: str,
    proposal_versions_sha256: str,
    spec: SQSResourceSpec,
) -> HandoffManifest:
    root.mkdir(parents=True, exist_ok=False)
    destination = root / "workspace"
    _copy_workspace(workspace, destination)
    files = tuple(_describe(destination))
    manifest = HandoffManifest(
        schema_version="1",
        proposal_sha=proposal_sha,
        executor_sha=executor_sha,
        pr_number=pr_number,
        repository_id=repository_id,
        request_id=request_id,
        proposal_main_sha256=proposal_main_sha256,
        proposal_versions_sha256=proposal_versions_sha256,
        canonical_inputs=CanonicalInputs.from_spec(spec),
        files=files,
    )
    _write_manifest(root / "manifest.json", manifest)
    _require_payload_limit(root)
    return manifest


def verify_handoff(
    root: Path, *, expected_executor_sha: str, module_source_dir: Path
) -> HandoffManifest:
    manifest = _read_manifest(root / "manifest.json")
    if manifest.schema_version != "1":
        raise HandoffRejected("manifest schema_version is not 1")
    if manifest.executor_sha != expected_executor_sha:
        raise HandoffRejected("executor SHA does not match this run", sha_mismatch=True)
    for item in manifest.files:
        _require_safe_path(item.path)
    listed = {item.path: item for item in manifest.files}
    observed = _observe(root)
    if set(observed) != set(listed):
        raise HandoffRejected("handoff paths do not match the manifest")
    for path, item in listed.items():
        actual = observed[path]
        if actual.is_symlink():
            raise HandoffRejected("symlink")
        blob = actual.read_bytes()
        if len(blob) != item.size or hashlib.sha256(blob).hexdigest() != item.sha256:
            raise HandoffRejected("hash mismatch")
    _require_payload_limit(root)
    spec = manifest.canonical_inputs.to_spec()
    with tempfile.TemporaryDirectory() as temporary:
        rebuilt = Path(temporary) / "workspace"
        build_v3_workspace(spec, module_source_dir=module_source_dir, destination=rebuilt)
        for path in rebuilt.rglob("*"):
            if not path.is_file():
                continue
            relative = Path("workspace") / path.relative_to(rebuilt)
            candidate = root / relative
            if candidate.read_bytes() != path.read_bytes():
                raise HandoffRejected("workspace bytes do not match the trusted re-render")
    return manifest


def _copy_workspace(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise HandoffRejected("symlink")
        relative = path.relative_to(source).as_posix()
        target = destination / relative
        _require_safe_path(f"workspace/{relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _describe(workspace: Path) -> list[HandoffFile]:
    described: list[HandoffFile] = []
    for path in sorted(item for item in workspace.rglob("*") if item.is_file()):
        relative = f"workspace/{path.relative_to(workspace).as_posix()}"
        blob = path.read_bytes()
        described.append(
            HandoffFile(
                path=relative,
                size=len(blob),
                sha256=hashlib.sha256(blob).hexdigest(),
            )
        )
    return described


def _write_manifest(path: Path, manifest: HandoffManifest) -> None:
    payload = {
        "schema_version": manifest.schema_version,
        "proposal_sha": manifest.proposal_sha,
        "executor_sha": manifest.executor_sha,
        "pr_number": manifest.pr_number,
        "repository_id": manifest.repository_id,
        "request_id": manifest.request_id,
        "proposal_main_sha256": manifest.proposal_main_sha256,
        "proposal_versions_sha256": manifest.proposal_versions_sha256,
        "canonical_inputs": manifest.canonical_inputs.to_json(),
        "files": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in manifest.files
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_manifest(path: Path) -> HandoffManifest:
    if path.is_symlink():
        raise HandoffRejected("symlink")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffRejected("manifest is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise HandoffRejected("manifest is not an object")
    files_payload = payload.get("files")
    if not isinstance(files_payload, list):
        raise HandoffRejected("manifest files are missing")
    files: list[HandoffFile] = []
    for item in files_payload:
        if not isinstance(item, dict):
            raise HandoffRejected("manifest file entry is not an object")
        try:
            files.append(
                HandoffFile(path=item["path"], size=item["size"], sha256=item["sha256"])
            )
        except (KeyError, TypeError) as exc:
            raise HandoffRejected("manifest file entry is incomplete") from exc
    try:
        return HandoffManifest(
            schema_version=payload["schema_version"],
            proposal_sha=payload["proposal_sha"],
            executor_sha=payload["executor_sha"],
            pr_number=payload["pr_number"],
            repository_id=payload["repository_id"],
            request_id=payload["request_id"],
            proposal_main_sha256=payload["proposal_main_sha256"],
            proposal_versions_sha256=payload["proposal_versions_sha256"],
            canonical_inputs=CanonicalInputs.from_json(payload.get("canonical_inputs")),
            files=tuple(files),
        )
    except KeyError as exc:
        raise HandoffRejected("manifest is missing a required field") from exc


def _require_safe_path(path: str) -> None:
    if not isinstance(path, str) or path.startswith("/") or Path(path).is_absolute():
        raise HandoffRejected("absolute path")
    if "\\" in path or ".." in Path(path).parts:
        raise HandoffRejected("parent segment")
    if path in _ROOT_FILES:
        return
    if path.startswith(_MODULE_PREFIX):
        name = path[len(_MODULE_PREFIX) :]
        if name.endswith(".tf") and "/" not in name and name not in {"", ".", ".."}:
            return
    raise HandoffRejected(f"path is not allowlisted: {path}")


def _observe(root: Path) -> dict[str, Path]:
    observed: dict[str, Path] = {}
    workspace = root / "workspace"
    if not workspace.is_dir() or workspace.is_symlink():
        raise HandoffRejected("workspace directory is missing")
    for path in workspace.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise HandoffRejected("symlink")
        if path.is_file():
            observed[relative] = path
        elif not path.is_dir():
            raise HandoffRejected("handoff contains a non-file entry")
    extras = [path for path in root.iterdir() if path.name != "manifest.json"]
    for extra in extras:
        if extra.name != "workspace":
            raise HandoffRejected("extra path")
    return observed


def _require_payload_limit(root: Path) -> None:
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise HandoffRejected("symlink")
        if path.is_file():
            total += path.stat().st_size
    if total > HANDOFF_MAX_BYTES:
        raise HandoffRejected("handoff payload exceeds 1 MiB")

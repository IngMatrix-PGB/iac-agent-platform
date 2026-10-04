"""Assemble the workspace Job B plans. The proposal file is not that workspace."""

from __future__ import annotations

import hashlib
from pathlib import Path

from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.providers.aws.terraform_render import (
    AWS_REGION,
    hcl_string,
    render_provider_block,
    render_versions_tf,
)

_HEADER = (
    "# GENERATED FILE — do not edit by hand.\n"
    "# Produced deterministically by TerraformCompositionRenderer from a\n"
    "# validated SQSResourceSpec. Regenerate instead of modifying.\n\n"
)
_MODULE_SOURCE = "./modules/sqs"


class WorkspaceError(ValueError):
    """The trusted workspace could not be assembled."""


def render_v3_provider_tf() -> str:
    return f'provider "aws" {{\n  region = {hcl_string(AWS_REGION)}\n}}\n'


def build_v3_workspace(
    spec: SQSResourceSpec,
    *,
    module_source_dir: Path,
    destination: Path,
) -> dict[str, str]:
    _reject_symlinks(module_source_dir)
    rendered = TerraformCompositionRenderer().render(spec, module_source=_MODULE_SOURCE)
    prefix = _HEADER + render_provider_block() + "\n"
    full_main = rendered.files["main.tf"]
    if not full_main.startswith(prefix):
        raise WorkspaceError("trusted renderer output did not start with the known provider")
    module_main = full_main[len(prefix) :]
    if 'provider "aws"' in module_main or "skip_credentials_validation" in module_main:
        raise WorkspaceError("reconstructed main.tf still contains the V1 provider")

    destination.mkdir(parents=True, exist_ok=False)
    (destination / "versions.tf").write_text(render_versions_tf(), encoding="utf-8")
    (destination / "provider.tf").write_text(render_v3_provider_tf(), encoding="utf-8")
    (destination / "main.tf").write_text(module_main, encoding="utf-8")
    _copy_tree(module_source_dir, destination / "modules" / "sqs")
    return _hashes(destination)


def _reject_symlinks(root: Path) -> None:
    if not root.is_dir():
        raise WorkspaceError(f"module directory does not exist: {root}")
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            raise WorkspaceError("trusted module directory contains a symlink")


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise WorkspaceError("trusted module directory contains a non-file entry")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes

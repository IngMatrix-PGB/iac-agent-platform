"""Application-controlled Terraform module directories."""

from __future__ import annotations

from pathlib import Path

from iac_agent.domain.resource import ResourceType

_MODULE_SEGMENTS: dict[ResourceType, str] = {
    ResourceType.SQS: "sqs",
    ResourceType.S3: "s3",
    ResourceType.DYNAMODB: "dynamodb",
    ResourceType.LAMBDA: "lambda",
    ResourceType.API_GATEWAY: "api_gateway",
    ResourceType.ECR: "ecr",
}


def checkout_module_root() -> Path:
    """Repository root when this file lives at ``src/iac_agent/graph/modules.py``."""
    return Path(__file__).resolve().parents[3]


def trusted_module_dirs(root: Path) -> dict[ResourceType, Path]:
    """Return the in-code module directories beneath ``root``.

    The request never chooses ``root`` or these paths.
    """
    resolved_root = root.resolve()
    dirs: dict[ResourceType, Path] = {}
    for resource_type, segment in _MODULE_SEGMENTS.items():
        path = (resolved_root / "terraform" / "modules" / segment).resolve()
        path.relative_to(resolved_root)
        if not path.is_dir():
            raise ValueError(f"trusted Terraform module is missing: {path}")
        dirs[resource_type] = path
    return dirs


def default_trusted_module_dirs() -> dict[ResourceType, Path]:
    from iac_agent.app.config import load_trusted_module_root

    return trusted_module_dirs(load_trusted_module_root())

#!/usr/bin/env python3
"""Classify a diff into CI validation shards.

The ownership table in this file is the policy. Matching does not read
Terraform modules or Python imports, and it does not call AWS.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SHARD_ORDER = (
    "s3",
    "sqs",
    "dynamodb",
    "ecr",
    "lambda",
    "api_gateway",
    "api_lambda",
    "api_lambda_dynamodb",
    "serverless_worker",
    "security",
)

SHARD_FILES = {
    "s3": (
        "test_s3_renderer_terraform.py",
        "test_s3_golden_real_tool_eval.py",
        "test_s3_workflow_integration.py",
        "test_s3_workflow_persistence.py",
    ),
    "sqs": (
        "test_sqs_renderer_terraform.py",
        "test_sqs_golden_real_tool_eval.py",
        "test_sqs_workflow_integration.py",
        "test_sqs_workflow_persistence.py",
        "test_sqs_workflow_hitl.py",
    ),
    "dynamodb": (
        "test_dynamodb_renderer_terraform.py",
        "test_dynamodb_golden_real_tool_eval.py",
        "test_dynamodb_workflow_integration.py",
        "test_dynamodb_workflow_persistence.py",
    ),
    "ecr": (
        "test_ecr_renderer_terraform.py",
        "test_ecr_golden_real_tool_eval.py",
        "test_ecr_workflow_persistence.py",
    ),
    "lambda": (
        "test_lambda_renderer_terraform.py",
        "test_lambda_golden_real_tool_eval.py",
        "test_lambda_workflow_integration.py",
        "test_lambda_workflow_persistence.py",
    ),
    "api_gateway": ("test_api_gateway_renderer_terraform.py",),
    "api_lambda": (
        "test_api_lambda_renderer_terraform.py",
        "test_api_lambda_golden_real_tool_eval.py",
        "test_api_lambda_workflow_integration.py",
        "test_api_lambda_workflow_persistence.py",
    ),
    "api_lambda_dynamodb": (
        "test_api_lambda_dynamodb_renderer_terraform.py",
        "test_api_lambda_dynamodb_golden_real_tool_eval.py",
        "test_api_lambda_dynamodb_workflow_persistence.py",
    ),
    "serverless_worker": (
        "test_serverless_worker_renderer_terraform.py",
        "test_serverless_worker_golden_real_tool_eval.py",
        "test_serverless_worker_workflow_integration.py",
        "test_serverless_worker_workflow_persistence.py",
        "test_application_composition.py",
        "test_cli_real_tool.py",
    ),
    "security": (
        "test_checkov_integration.py",
        "test_security_gate_integration.py",
        "test_platform_policy_integration.py",
        "test_plan_analyzer_integration.py",
        "test_terraform_runner_integration.py",
    ),
}

SHARD_CONSUMES = {
    "s3": frozenset({"s3"}),
    "sqs": frozenset({"sqs"}),
    "dynamodb": frozenset({"dynamodb"}),
    "ecr": frozenset({"ecr"}),
    "lambda": frozenset({"lambda"}),
    "api_gateway": frozenset({"api_gateway"}),
    "api_lambda": frozenset({"api_gateway", "lambda"}),
    "api_lambda_dynamodb": frozenset({"api_gateway", "lambda", "dynamodb"}),
    "serverless_worker": frozenset({"sqs", "lambda", "dynamodb"}),
    "security": frozenset({"sqs"}),
}

_ALL_SHARDS = frozenset(SHARD_ORDER)

_SHARED_PREFIXES = (
    "src/iac_agent/graph/",
    "src/iac_agent/execution/",
    "src/iac_agent/security/",
    "src/iac_agent/policies/",
    "src/iac_agent/app/",
)

_SHARED_FILES = frozenset(
    {
        "src/iac_agent/providers/aws/renderer.py",
        "src/iac_agent/providers/aws/resource.py",
        "src/iac_agent/providers/aws/terraform_render.py",
        "src/iac_agent/providers/aws/__init__.py",
    }
)

_MODULE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("terraform/modules/s3/", "s3"),
    ("terraform/modules/sqs/", "sqs"),
    ("terraform/modules/dynamodb/", "dynamodb"),
    ("terraform/modules/ecr/", "ecr"),
    ("terraform/modules/lambda/", "lambda"),
    ("terraform/modules/api_gateway/", "api_gateway"),
    ("src/iac_agent/providers/aws/s3/", "s3"),
    ("src/iac_agent/providers/aws/sqs/", "sqs"),
    ("src/iac_agent/providers/aws/dynamodb/", "dynamodb"),
    ("src/iac_agent/providers/aws/ecr/", "ecr"),
    ("src/iac_agent/providers/aws/api_gateway/", "api_gateway"),
    ("src/iac_agent/providers/aws/lambda_function/", "lambda"),
    ("tests/terraform/s3/", "s3"),
    ("tests/terraform/sqs/", "sqs"),
)

_COMPOSITION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("src/iac_agent/compositions/api_lambda_dynamodb/", "api_lambda_dynamodb"),
    ("src/iac_agent/compositions/api_lambda/", "api_lambda"),
    ("src/iac_agent/compositions/serverless_worker/", "serverless_worker"),
)

_KMS_PATH = "src/iac_agent/providers/aws/kms.py"
_KMS_MODULES = frozenset({"s3", "sqs"})
_BOOTSTRAP_TEST = "tests/integration/test_bootstrap_aws_oidc_terraform.py"
_WORKFLOW_PREFIX = ".github/workflows/"

_REASON_SHARED = "shared product path"
_REASON_UNKNOWN = "unknown path"
_REASON_WORKFLOW = "workflow change"
_REASON_EMPTY = "empty diff"
_REASON_UNREADABLE = "unreadable diff"
_REASON_FAILURE = "classifier failure"
_REASON_FRONTEND = "frontend change"
_REASON_BOOTSTRAP = "bootstrap change"


def _file_owners() -> dict[str, str]:
    owners: dict[str, str] = {}
    for shard, files in SHARD_FILES.items():
        for name in files:
            owners[name] = shard
    return owners


_FILE_OWNERS = _file_owners()


class Selection:
    """Shard selection. A plain class so the test loader can exec this file."""

    __slots__ = ("shards", "bootstrap", "frontend", "full", "reasons")

    def __init__(
        self,
        shards: frozenset[str],
        bootstrap: bool,
        frontend: bool,
        full: bool,
        reasons: tuple[str, ...],
    ) -> None:
        self.shards = shards
        self.bootstrap = bootstrap
        self.frontend = frontend
        self.full = full
        self.reasons = reasons


class _Effect:
    __slots__ = ("modules", "direct", "bootstrap", "frontend", "shared", "unknown")

    def __init__(
        self,
        modules: frozenset[str] = frozenset(),
        direct: frozenset[str] = frozenset(),
        *,
        bootstrap: bool = False,
        frontend: bool = False,
        shared: bool = False,
        unknown: bool = False,
    ) -> None:
        self.modules = modules
        self.direct = direct
        self.bootstrap = bootstrap
        self.frontend = frontend
        self.shared = shared
        self.unknown = unknown


def _normalize(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").strip().split("/") if part not in {"", "."}]
    return "/".join(parts)


def _match_prefix(path: str, prefix: str) -> bool:
    base = prefix.rstrip("/")
    return path == base or path.startswith(f"{base}/")


def _selection(
    shards: frozenset[str],
    *,
    bootstrap: bool,
    frontend: bool,
    reasons: tuple[str, ...],
) -> Selection:
    return Selection(
        shards=shards,
        bootstrap=bootstrap,
        frontend=frontend,
        full=shards == _ALL_SHARDS,
        reasons=reasons,
    )


def _closed(reason: str) -> Selection:
    return _selection(
        _ALL_SHARDS,
        bootstrap=True,
        frontend=True,
        reasons=(reason,),
    )


def _classify_one(path: str) -> _Effect:
    if not path:
        return _Effect(unknown=True)
    if path == "README.md" or _match_prefix(path, "docs/"):
        return _Effect()
    if _match_prefix(path, "ui/"):
        return _Effect(frontend=True)
    if path == _BOOTSTRAP_TEST or _match_prefix(path, "bootstrap/aws-oidc/"):
        return _Effect(bootstrap=True)
    if path in _SHARED_FILES or any(_match_prefix(path, prefix) for prefix in _SHARED_PREFIXES):
        return _Effect(shared=True)
    if path == _KMS_PATH:
        return _Effect(modules=_KMS_MODULES)
    for prefix, module_name in _MODULE_PREFIXES:
        if _match_prefix(path, prefix):
            return _Effect(modules=frozenset({module_name}))
    for prefix, shard in _COMPOSITION_PREFIXES:
        if _match_prefix(path, prefix):
            return _Effect(direct=frozenset({shard}))
    owner = _FILE_OWNERS.get(Path(path).name)
    if owner is not None:
        return _Effect(direct=frozenset({owner}))
    return _Effect(unknown=True)


def classify(paths: list[str] | None, *, failed: bool = False) -> Selection:
    if failed:
        return _closed(_REASON_FAILURE)
    if paths is None:
        return _closed(_REASON_UNREADABLE)
    if not paths:
        return _closed(_REASON_EMPTY)

    normalized = [_normalize(path) for path in paths]
    if any(_match_prefix(path, _WORKFLOW_PREFIX) for path in normalized):
        return _closed(_REASON_WORKFLOW)

    modules: set[str] = set()
    direct: set[str] = set()
    bootstrap = False
    frontend = False
    shared = False
    unknown = False
    for path in normalized:
        effect = _classify_one(path)
        modules.update(effect.modules)
        direct.update(effect.direct)
        bootstrap = bootstrap or effect.bootstrap
        frontend = frontend or effect.frontend
        shared = shared or effect.shared
        unknown = unknown or effect.unknown

    direct.update(name for name in modules if name in _ALL_SHARDS)
    closure = {
        shard for shard, consumes in SHARD_CONSUMES.items() if consumes & modules
    }
    selected = set(direct) | closure
    if shared or unknown:
        selected = set(_ALL_SHARDS)
    transitive = closure - direct

    reasons: set[str] = set()
    if shared:
        reasons.add(_REASON_SHARED)
    if unknown:
        reasons.add(_REASON_UNKNOWN)
    if frontend:
        reasons.add(_REASON_FRONTEND)
    if bootstrap:
        reasons.add(_REASON_BOOTSTRAP)
    reasons.update(f"direct:{shard}" for shard in direct)
    reasons.update(f"transitive:{shard}" for shard in transitive)
    return _selection(
        frozenset(selected),
        bootstrap=bootstrap,
        frontend=frontend,
        reasons=tuple(sorted(reasons)),
    )


def _flag(value: bool) -> str:
    return "true" if value else "false"


def format_github_output(selection: Selection) -> str:
    lines = [f"{shard}={_flag(shard in selection.shards)}" for shard in SHARD_ORDER]
    lines.append(f"bootstrap={_flag(selection.bootstrap)}")
    lines.append(f"frontend={_flag(selection.frontend)}")
    lines.append(f"full={_flag(selection.full)}")
    lines.append("reasons=" + ",".join(selection.reasons))
    return "\n".join(lines) + "\n"


def format_summary(selection: Selection, paths: list[str]) -> str:
    selected = [shard for shard in SHARD_ORDER if shard in selection.shards]
    skipped = [shard for shard in SHARD_ORDER if shard not in selection.shards]

    def _names(names: list[str]) -> str:
        return ", ".join(names) if names else "(none)"

    path_lines = "\n".join(f"- `{path}`" for path in paths) if paths else "- (none)"
    reasons = ", ".join(selection.reasons) if selection.reasons else "(none)"
    return "\n".join(
        [
            "## CI validation classification",
            "",
            "Paths:",
            path_lines,
            "",
            f"Selected shards: {_names(selected)}",
            f"Skipped shards: {_names(skipped)}",
            f"Bootstrap: {_flag(selection.bootstrap)}",
            f"Frontend: {_flag(selection.frontend)}",
            f"Reasons: {reasons}",
            "",
        ]
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Classify changed paths into CI validation shards."
    )
    parser.add_argument("--paths-file", required=True)
    parser.add_argument("--github-output")
    parser.add_argument("--step-summary")
    parser.add_argument("--unreadable", action="store_true")
    args = parser.parse_args(argv)

    paths_file = Path(args.paths_file)
    if not paths_file.is_file():
        return 2

    if args.unreadable:
        selection = classify(None)
        classified_paths: list[str] = []
    else:
        raw = paths_file.read_text(encoding="utf-8")
        if raw == "":
            classified_paths = []
            selection = classify([])
        else:
            classified_paths = [line.strip() for line in raw.splitlines() if line.strip()]
            selection = classify(classified_paths)

    if args.github_output:
        Path(args.github_output).write_text(
            format_github_output(selection),
            encoding="utf-8",
        )
    if args.step_summary:
        Path(args.step_summary).write_text(
            format_summary(selection, classified_paths),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""The Checkov security-scanner execution boundary.

`CheckovAdapter.scan(workspace)` is the only place this project shells
out to the Checkov CLI. It does not render Terraform, execute
Terraform, interpret a `PlanSummary`, call platform policies, invoke an
LLM, or touch Git — it only runs Checkov against an explicit workspace
directory and returns a normalized, review-safe result.

Hard invariant verified empirically against the installed Checkov
3.3.13 CLI before writing this module: Checkov exits **1**, not 0,
when it completes a scan that found failed checks — a non-zero exit
code is NOT itself evidence of scanner failure. This adapter treats
exit codes {0, 1} as "the scan ran" and anything else as a genuine
execution failure, then separately verifies the JSON payload is
well-formed and internally consistent before trusting it.

Batch 16.5: `scan()` takes an explicit, optional `CheckovScanProfile`
rather than a resource type or a constructor-level default skip list.
This module deliberately has no knowledge of SQS, S3, or any other
resource type — `iac_agent.security.checkov_profiles` is the one place
that maps a resource type to a specific profile. A caller that passes
no profile always gets the strict, zero-skip scan; there is no
implicit global skip list here.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)

#: Same allowlist rationale as TerraformRunner: PATH is required for
#: subprocess.run to resolve the bare "checkov" executable name at all;
#: HOME covers Checkov's own local config/cache lookup. Nothing else is
#: copied from the host by default.
_DEFAULT_ENV_ALLOWLIST = ("PATH", "HOME")

_DEFAULT_TIMEOUT_SECONDS = 120.0

#: Checkov exits 0 for a clean scan and 1 when it found failed checks —
#: both are "the scan completed", verified empirically. Any other exit
#: code (e.g. 2 for a CLI usage error) means Checkov did not perform
#: the scan we asked for at all.
_SCAN_COMPLETED_EXIT_CODES = (0, 1)

_SEVERITY_MAP: dict[str, SecuritySeverity] = {
    "info": SecuritySeverity.INFO,
    "low": SecuritySeverity.LOW,
    "medium": SecuritySeverity.MEDIUM,
    "high": SecuritySeverity.HIGH,
    "critical": SecuritySeverity.CRITICAL,
}

#: Checkov does not populate a severity for local/offline terraform
#: framework scans (verified empirically — every failed check observed
#: had severity=null). A failed check being treated as blocking in
#: Phase 1 should never present as merely informational, so an absent
#: or unrecognized severity defaults to HIGH rather than the lowest tier.
_DEFAULT_FAILED_CHECK_SEVERITY = SecuritySeverity.HIGH

_STDERR_EXCERPT_LIMIT = 500


@dataclass(frozen=True)
class CheckovScanProfile:
    """An explicit, resource-agnostic Checkov scan configuration.

    `CheckovAdapter` never infers a resource type or hardcodes a
    default skip list itself (Batch 16.5) — it only knows how to apply
    whatever profile a caller explicitly hands to `scan()`. The one
    place that maps a resource type to a specific profile (and the
    rationale for each skipped check) is
    `iac_agent.security.checkov_profiles.checkov_profile_for`, not this
    module. A caller that passes no profile at all always gets the
    strict, zero-skip scan — there is no implicit global default here.
    """

    skipped_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckovScanResult:
    """A normalized, review-safe Checkov scan outcome.

    Deliberately excludes raw Checkov JSON, full `code_block` source
    excerpts, and absolute file paths — only normalized
    `SecurityFinding` values (source=CHECKOV) and aggregate counts are
    kept. Passed checks are counted but never individually surfaced as
    findings (Checkov can report dozens of passes per resource; doing
    so for every one would swamp the normalized finding set).
    """

    findings: tuple[SecurityFinding, ...]
    passed_checks: int
    failed_checks: int
    skipped_checks: int
    scanner_version: str | None

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(self.findings, key=lambda f: (f.policy_id, f.resource or "", f.message))
        )
        object.__setattr__(self, "findings", normalized)


class CheckovError(Exception):
    """Base class for all Checkov adapter errors."""


class CheckovExecutableNotFoundError(CheckovError):
    """The configured Checkov binary could not be found/executed."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"checkov executable not found or not executable: {binary!r}")


class CheckovTimeoutError(CheckovError):
    """A Checkov scan exceeded its configured timeout."""

    def __init__(self, command: tuple[str, ...], timeout_seconds: float) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        super().__init__(f"checkov scan timed out after {timeout_seconds}s: {' '.join(command)}")


class CheckovExecutionError(CheckovError):
    """The scanner itself did not complete a trustworthy scan.

    This is distinct from a scan that ran to completion and reported
    failed security checks — that is a normal `CheckovScanResult`, not
    an error. Raised for: an exit code outside {0, 1}; Checkov
    reporting `parsing_errors > 0` (part of the workspace was never
    actually analyzed); or the reported failed-check count disagreeing
    with the number of normalized failed-check entries.
    """


class CheckovJsonError(CheckovError):
    """Checkov's stdout was not valid JSON, or not a recognized shape."""

    def __init__(self, command: tuple[str, ...], cause: Exception) -> None:
        self.command = command
        self.cause = cause
        super().__init__(
            f"checkov output could not be safely parsed ({' '.join(command)}): {cause}"
        )


def _require_workspace(workspace: Path | str) -> Path:
    path = Path(workspace)
    if not path.exists():
        raise ValueError(f"workspace does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"workspace is not a directory: {path}")
    return path


def _safe_stderr_excerpt(stderr: str) -> str:
    return stderr.strip()[:_STDERR_EXCERPT_LIMIT]


class CheckovAdapter:
    """Runs Checkov against a Terraform workspace and normalizes the result.

    Holds no reference to a Terraform runner, plan, or resource spec —
    purely an execution boundary, mirroring `TerraformRunner`.
    """

    def __init__(
        self,
        checkov_binary: str = "checkov",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        self._binary = checkov_binary
        self._timeout_seconds = timeout_seconds
        self._base_env: dict[str, str] = (
            dict(base_env) if base_env is not None else self._default_base_env()
        )

    @staticmethod
    def _default_base_env() -> dict[str, str]:
        return {key: os.environ[key] for key in _DEFAULT_ENV_ALLOWLIST if key in os.environ}

    def scan(
        self, workspace: Path | str, *, profile: CheckovScanProfile | None = None
    ) -> CheckovScanResult:
        """Run Checkov against `workspace` and return a normalized result.

        `profile` is optional and defaults to `None` — a caller that
        passes no profile always gets the strict, zero-skip scan; this
        adapter never infers a resource type or applies a skip list on
        its own (see `iac_agent.security.checkov_profiles` for the one
        place that maps a resource type to a specific profile).

        Raises `CheckovExecutableNotFoundError`, `CheckovTimeoutError`,
        `CheckovExecutionError`, or `CheckovJsonError` if the scan could
        not be trusted — never a `CheckovScanResult` claiming a clean
        scan in any of those cases.
        """
        ws = _require_workspace(workspace)
        args = (
            self._binary,
            "-d",
            ".",
            "--framework",
            "terraform",
            "-o",
            "json",
            "--compact",
            "--quiet",
        )
        if profile is not None and profile.skipped_checks:
            args = (*args, "--skip-check", ",".join(profile.skipped_checks))

        try:
            completed = subprocess.run(  # noqa: S603 — argument array, shell=False, fixed args
                args,
                cwd=ws,
                env=dict(self._base_env),
                shell=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise CheckovExecutableNotFoundError(self._binary) from exc
        except subprocess.TimeoutExpired as exc:
            raise CheckovTimeoutError(command=args, timeout_seconds=self._timeout_seconds) from exc

        return _parse_checkov_output(args, completed.returncode, completed.stdout, completed.stderr)


def _parse_checkov_output(
    command: tuple[str, ...], returncode: int, stdout: str, stderr: str
) -> CheckovScanResult:
    if returncode not in _SCAN_COMPLETED_EXIT_CODES:
        raise CheckovExecutionError(
            f"checkov exited with unexpected status {returncode}: {_safe_stderr_excerpt(stderr)}"
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CheckovJsonError(command=command, cause=exc) from exc

    summary, raw_failed_checks = _extract_summary_and_failed_checks(command, payload)

    parsing_errors = summary.get("parsing_errors", 0)
    if not isinstance(parsing_errors, int) or isinstance(parsing_errors, bool):
        raise CheckovJsonError(
            command=command, cause=ValueError("summary.parsing_errors must be an integer")
        )
    if parsing_errors > 0:
        raise CheckovExecutionError(
            f"checkov reported {parsing_errors} parsing error(s); the scan did not complete "
            "cleanly for the entire workspace"
        )

    passed = _require_int(command, summary, "passed")
    failed = _require_int(command, summary, "failed")
    skipped = _require_int(command, summary, "skipped")

    findings = tuple(_normalize_failed_check(command, entry) for entry in raw_failed_checks)

    if len(findings) != failed:
        raise CheckovExecutionError(
            f"checkov summary reports {failed} failed check(s) but {len(findings)} "
            "failed_checks entries were present — treating this as untrustworthy output"
        )

    scanner_version = summary.get("checkov_version")
    if scanner_version is not None and not isinstance(scanner_version, str):
        scanner_version = None

    return CheckovScanResult(
        findings=findings,
        passed_checks=passed,
        failed_checks=failed,
        skipped_checks=skipped,
        scanner_version=scanner_version,
    )


def _extract_summary_and_failed_checks(
    command: tuple[str, ...], payload: Any
) -> tuple[dict[str, Any], list[Any]]:
    """Support the two top-level shapes observed from the installed
    Checkov CLI: a single-framework result object (`summary` +
    `results.failed_checks`), and a bare summary-only object emitted
    when no resources of the requested framework were found at all."""
    if not isinstance(payload, dict):
        raise CheckovJsonError(
            command=command,
            cause=TypeError(f"expected a JSON object, got {type(payload).__name__}"),
        )

    if "summary" in payload:
        summary = payload["summary"]
        if not isinstance(summary, dict):
            raise CheckovJsonError(command=command, cause=TypeError("'summary' must be an object"))
        results = payload.get("results", {})
        if not isinstance(results, dict):
            raise CheckovJsonError(command=command, cause=TypeError("'results' must be an object"))
        failed_checks = results.get("failed_checks", [])
        if not isinstance(failed_checks, list):
            raise CheckovJsonError(
                command=command, cause=TypeError("'results.failed_checks' must be a list")
            )
        return summary, failed_checks

    if "passed" in payload and "failed" in payload:
        return payload, []

    raise CheckovJsonError(command=command, cause=ValueError("unrecognized checkov output shape"))


def _require_int(command: tuple[str, ...], summary: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CheckovJsonError(
            command=command, cause=ValueError(f"summary.{key} must be an integer")
        )
    return value


def _normalize_failed_check(command: tuple[str, ...], entry: Any) -> SecurityFinding:
    if not isinstance(entry, dict):
        raise CheckovJsonError(
            command=command,
            cause=TypeError(f"failed_checks entry must be an object, got {type(entry).__name__}"),
        )

    check_id = entry.get("check_id")
    if not isinstance(check_id, str) or not check_id:
        raise CheckovJsonError(
            command=command, cause=ValueError("failed_checks entry is missing a valid 'check_id'")
        )

    # `resource` (e.g. "module.queue.aws_sqs_queue.this") is Checkov's
    # own Terraform-address form and is safe to surface as-is. Only
    # `file_path` (already relative, e.g. "/main.tf") is read for the
    # message below — `file_abs_path`/`definition_context_file_path`
    # (absolute developer paths) and `code_block` (raw source lines)
    # are deliberately never read anywhere in this function.
    resource = entry.get("resource")
    resource = resource if isinstance(resource, str) and resource else None

    check_name = entry.get("check_name")
    check_name = " ".join(check_name.split()) if isinstance(check_name, str) else None

    severity = _map_severity(entry.get("severity"))

    return SecurityFinding(
        policy_id=check_id,
        severity=severity,
        status=PolicyStatus.BLOCK,
        resource=resource,
        message=_build_message(check_id, resource, check_name),
        source=FindingSource.CHECKOV,
    )


def _build_message(check_id: str, resource: str | None, check_name: str | None) -> str:
    if resource and check_name:
        return f"Checkov {check_id} failed for {resource}: {check_name}."
    if resource:
        return f"Checkov {check_id} failed for {resource}."
    if check_name:
        return f"Checkov {check_id} failed: {check_name}."
    return f"Checkov {check_id} failed."


def _map_severity(raw: Any) -> SecuritySeverity:
    if isinstance(raw, str):
        mapped = _SEVERITY_MAP.get(raw.strip().lower())
        if mapped is not None:
            return mapped
    return _DEFAULT_FAILED_CHECK_SEVERITY

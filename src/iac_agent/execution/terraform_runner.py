"""The single controlled boundary for invoking the Terraform CLI.

TerraformRunner executes exactly five allowlisted Terraform operations
(fmt, init, validate, plan, show -json) as argument-array subprocess
calls (never a shell). It has no knowledge of SQS, Terraform plan
semantics, security policy, Git, or the AWS API — it only knows how to
run Terraform safely against an explicit workspace directory and hand
back a structured result. There is no public method that accepts an
arbitrary Terraform subcommand, and `apply`/`destroy` do not exist here
in any form.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Host environment variables copied into the subprocess environment by
#: default. PATH is required for subprocess.run to resolve a bare
#: executable name at all (verified empirically — without it, Python
#: raises FileNotFoundError even when the binary is genuinely on disk).
#: HOME is required for Terraform's own CLI config / plugin cache
#: lookup. Nothing else is copied from the host by default.
_DEFAULT_ENV_ALLOWLIST = ("PATH", "HOME")

_DEFAULT_PLAN_FILENAME = "tfplan"


@dataclass(frozen=True)
class CommandResult:
    """The outcome of one Terraform subprocess invocation.

    Deliberately excludes the subprocess environment — only the exact
    argv, exit code, captured output, and wall-clock duration are kept.
    """

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class TerraformError(Exception):
    """Base class for all TerraformRunner errors."""


class TerraformExecutableNotFoundError(TerraformError):
    """The configured Terraform binary could not be found/executed."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"terraform executable not found or not executable: {binary!r}")


class TerraformTimeoutError(TerraformError):
    """A Terraform command exceeded its configured timeout."""

    def __init__(self, command: tuple[str, ...], timeout_seconds: float) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"terraform command timed out after {timeout_seconds}s: {' '.join(command)}"
        )


class TerraformCommandError(TerraformError):
    """Terraform ran and returned a non-zero exit status."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"terraform command failed (exit {result.returncode}): "
            f"{' '.join(result.command)}\n{result.stderr.strip()}"
        )


class TerraformJsonError(TerraformError):
    """`terraform show -json` exited successfully but stdout was not valid JSON."""

    def __init__(self, command: tuple[str, ...], cause: Exception) -> None:
        self.command = command
        self.cause = cause
        super().__init__(
            f"terraform show -json output could not be decoded as JSON "
            f"({' '.join(command)}): {cause}"
        )


@dataclass(frozen=True)
class TerraformTimeouts:
    """Per-operation timeouts, in seconds."""

    fmt: float = 30.0
    init: float = 180.0
    validate: float = 30.0
    plan: float = 180.0
    show: float = 30.0


def _require_workspace(workspace: Path | str) -> Path:
    path = Path(workspace)
    if not path.exists():
        raise ValueError(f"workspace does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"workspace is not a directory: {path}")
    return path


def _require_safe_plan_filename(plan_filename: str) -> str:
    candidate = Path(plan_filename)
    if candidate.is_absolute():
        raise ValueError(f"plan_filename must be a relative path, got {plan_filename!r}")
    if candidate.name != plan_filename or ".." in candidate.parts:
        raise ValueError(
            "plan_filename must be a simple filename with no path separators "
            f"or parent-directory references, got {plan_filename!r}"
        )
    return plan_filename


class TerraformRunner:
    """Executes an allowlisted set of Terraform CLI operations.

    Holds no reference to any generated composition, resource spec, or
    security policy — it is purely an execution boundary.
    """

    def __init__(
        self,
        terraform_binary: str = "terraform",
        timeouts: TerraformTimeouts | None = None,
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        self._binary = terraform_binary
        self._timeouts = timeouts or TerraformTimeouts()
        self._base_env: dict[str, str] = (
            dict(base_env) if base_env is not None else self._default_base_env()
        )

    @staticmethod
    def _default_base_env() -> dict[str, str]:
        return {key: os.environ[key] for key in _DEFAULT_ENV_ALLOWLIST if key in os.environ}

    def _merged_env(self, env_overrides: Mapping[str, str] | None) -> dict[str, str]:
        merged = dict(self._base_env)
        if env_overrides:
            merged.update(env_overrides)
        return merged

    def _run(
        self,
        args: tuple[str, ...],
        workspace: Path,
        timeout: float,
        env_overrides: Mapping[str, str] | None,
    ) -> CommandResult:
        env = self._merged_env(env_overrides)
        start = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603 — argument array, shell=False, fixed args
                args,
                cwd=workspace,
                env=env,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise TerraformExecutableNotFoundError(self._binary) from exc
        except subprocess.TimeoutExpired as exc:
            raise TerraformTimeoutError(command=args, timeout_seconds=timeout) from exc
        duration = time.monotonic() - start
        return CommandResult(
            command=args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )

    def _run_checked(
        self,
        args: tuple[str, ...],
        workspace: Path,
        timeout: float,
        env_overrides: Mapping[str, str] | None,
    ) -> CommandResult:
        result = self._run(args, workspace, timeout, env_overrides)
        if result.returncode != 0:
            raise TerraformCommandError(result)
        return result

    def fmt(
        self,
        workspace: Path | str,
        *,
        env_overrides: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run `terraform fmt -check` — verifies formatting, never rewrites files."""
        ws = _require_workspace(workspace)
        args = (self._binary, "fmt", "-check", "-no-color")
        return self._run_checked(args, ws, self._timeouts.fmt, env_overrides)

    def init(
        self,
        workspace: Path | str,
        *,
        env_overrides: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run `terraform init -backend=false` non-interactively."""
        ws = _require_workspace(workspace)
        args = (self._binary, "init", "-backend=false", "-input=false", "-no-color")
        return self._run_checked(args, ws, self._timeouts.init, env_overrides)

    def validate(
        self,
        workspace: Path | str,
        *,
        env_overrides: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run `terraform validate`."""
        ws = _require_workspace(workspace)
        args = (self._binary, "validate", "-no-color")
        return self._run_checked(args, ws, self._timeouts.validate, env_overrides)

    def plan(
        self,
        workspace: Path | str,
        plan_filename: str = _DEFAULT_PLAN_FILENAME,
        *,
        env_overrides: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run `terraform plan -out=<plan_filename>`. Never applies anything."""
        ws = _require_workspace(workspace)
        safe_filename = _require_safe_plan_filename(plan_filename)
        args = (self._binary, "plan", "-input=false", "-no-color", f"-out={safe_filename}")
        return self._run_checked(args, ws, self._timeouts.plan, env_overrides)

    def show_json(
        self,
        workspace: Path | str,
        plan_filename: str = _DEFAULT_PLAN_FILENAME,
        *,
        env_overrides: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run `terraform show -json <plan_filename>` and decode the result.

        Returns the raw decoded JSON structure with no interpretation —
        resource-change/destructive-action semantics belong to a later
        plan-analysis layer, not to this execution boundary.
        """
        ws = _require_workspace(workspace)
        safe_filename = _require_safe_plan_filename(plan_filename)
        args = (self._binary, "show", "-json", safe_filename)
        result = self._run_checked(args, ws, self._timeouts.show, env_overrides)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise TerraformJsonError(command=args, cause=exc) from exc

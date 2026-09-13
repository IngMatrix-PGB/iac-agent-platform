"""Unit tests for TerraformRunner.

The subprocess boundary is mocked throughout — no real `terraform`
binary is required to run this file. Real-binary behavior is proven
separately by tests/integration/test_terraform_runner_integration.py.
"""

from __future__ import annotations

import inspect
import subprocess
from unittest.mock import patch

import pytest

from iac_agent.execution.terraform_runner import (
    CommandResult,
    TerraformCommandError,
    TerraformError,
    TerraformExecutableNotFoundError,
    TerraformJsonError,
    TerraformRunner,
    TerraformTimeoutError,
    TerraformTimeouts,
)

RUN_TARGET = "iac_agent.execution.terraform_runner.subprocess.run"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def runner():
    return TerraformRunner(base_env={"PATH": "/usr/bin", "HOME": "/home/test"})


# ---------------------------------------------------------------------------
# Exact argv construction
# ---------------------------------------------------------------------------


def test_fmt_builds_exact_expected_argv(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.fmt(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == ("terraform", "fmt", "-check", "-no-color")


def test_init_includes_backend_false(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.init(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == ("terraform", "init", "-backend=false", "-input=false", "-no-color")


def test_validate_builds_exact_expected_argv(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.validate(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == ("terraform", "validate", "-no-color")


def test_plan_builds_exact_expected_argv(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.plan(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == ("terraform", "plan", "-input=false", "-no-color", "-out=tfplan")


def test_show_json_builds_exact_expected_argv(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed(stdout="{}")) as mock_run:
        runner.show_json(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == ("terraform", "show", "-json", "tfplan")


# ---------------------------------------------------------------------------
# subprocess invocation safety
# ---------------------------------------------------------------------------


def test_shell_is_never_true(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.validate(workspace)

    _, kwargs = mock_run.call_args
    assert kwargs["shell"] is False


def test_explicit_cwd_is_passed(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.validate(workspace)

    _, kwargs = mock_run.call_args
    assert kwargs["cwd"] == workspace


def test_configured_timeout_is_passed(workspace):
    custom = TerraformTimeouts(validate=7.5)
    runner = TerraformRunner(timeouts=custom, base_env={"PATH": "/usr/bin"})

    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.validate(workspace)

    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 7.5


# ---------------------------------------------------------------------------
# Workspace validation happens before subprocess invocation
# ---------------------------------------------------------------------------


def test_nonexistent_workspace_fails_before_subprocess_invocation(runner, tmp_path):
    missing = tmp_path / "does-not-exist"

    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError, match="does not exist"):
            runner.validate(missing)

    mock_run.assert_not_called()


def test_workspace_pointing_to_a_file_is_rejected(runner, tmp_path):
    a_file = tmp_path / "not-a-directory.txt"
    a_file.write_text("hello")

    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError, match="not a directory"):
            runner.validate(a_file)

    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Result / error mapping
# ---------------------------------------------------------------------------


def test_successful_command_produces_command_result(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed(returncode=0, stdout="ok", stderr="")):
        result = runner.validate(workspace)

    assert isinstance(result, CommandResult)
    assert result.returncode == 0
    assert result.stdout == "ok"
    assert result.command == ("terraform", "validate", "-no-color")
    assert result.duration_seconds >= 0


def test_non_zero_exit_raises_terraform_command_error(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stderr="boom")):
        with pytest.raises(TerraformCommandError) as exc_info:
            runner.validate(workspace)

    assert exc_info.value.result.returncode == 1
    assert "boom" in str(exc_info.value)


def test_missing_executable_raises_not_found_error(runner, workspace):
    with patch(RUN_TARGET, side_effect=FileNotFoundError()):
        with pytest.raises(TerraformExecutableNotFoundError):
            runner.validate(workspace)


def test_subprocess_timeout_raises_terraform_timeout_error(runner, workspace):
    with patch(
        RUN_TARGET,
        side_effect=subprocess.TimeoutExpired(cmd=["terraform", "validate"], timeout=30.0),
    ):
        with pytest.raises(TerraformTimeoutError) as exc_info:
            runner.validate(workspace)

    assert exc_info.value.timeout_seconds == 30.0


def test_show_json_valid_json_returns_decoded_object(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed(stdout='{"format_version": "1.2"}')):
        decoded = runner.show_json(workspace)

    assert decoded == {"format_version": "1.2"}


def test_show_json_malformed_json_raises_terraform_json_error(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed(stdout="not json {{{")):
        with pytest.raises(TerraformJsonError):
            runner.show_json(workspace)


def test_all_custom_exceptions_are_terraform_errors():
    for exc_cls in (
        TerraformExecutableNotFoundError,
        TerraformTimeoutError,
        TerraformCommandError,
        TerraformJsonError,
    ):
        assert issubclass(exc_cls, TerraformError)


# ---------------------------------------------------------------------------
# Environment handling
# ---------------------------------------------------------------------------


def test_environment_override_is_passed_to_subprocess(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.plan(workspace, env_overrides={"AWS_ACCESS_KEY_ID": "test"})

    _, kwargs = mock_run.call_args
    assert kwargs["env"]["AWS_ACCESS_KEY_ID"] == "test"
    # Base env is still present alongside the override.
    assert kwargs["env"]["PATH"] == "/usr/bin"


def test_caller_environment_mappings_are_not_mutated(workspace):
    base_env = {"PATH": "/usr/bin", "HOME": "/home/test"}
    overrides = {"AWS_ACCESS_KEY_ID": "test"}
    runner = TerraformRunner(base_env=base_env)

    with patch(RUN_TARGET, return_value=_completed()):
        runner.plan(workspace, env_overrides=overrides)

    assert base_env == {"PATH": "/usr/bin", "HOME": "/home/test"}
    assert overrides == {"AWS_ACCESS_KEY_ID": "test"}


def test_environment_override_values_never_appear_in_command_args(runner, workspace):
    secret = "super-secret-value-xyz"
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.plan(workspace, env_overrides={"AWS_SECRET_ACCESS_KEY": secret})

    args, _ = mock_run.call_args
    assert secret not in args[0]
    assert all(secret not in part for part in args[0])


def test_secret_shaped_env_value_does_not_appear_in_exception_text(runner, workspace):
    secret = "super-secret-value-xyz"
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stderr="generic failure")):
        with pytest.raises(TerraformCommandError) as exc_info:
            runner.plan(workspace, env_overrides={"AWS_SECRET_ACCESS_KEY": secret})

    assert secret not in str(exc_info.value)


def test_runner_repr_does_not_expose_base_env_values():
    runner = TerraformRunner(base_env={"PATH": "/usr/bin", "HOME": "/home/super-secret-user"})
    assert "super-secret-user" not in repr(runner)


# ---------------------------------------------------------------------------
# Plan filename safety
# ---------------------------------------------------------------------------


def test_default_plan_filename_is_workspace_local(runner, workspace):
    with patch(RUN_TARGET, return_value=_completed()) as mock_run:
        runner.plan(workspace)

    args, _ = mock_run.call_args
    assert args[0][-1] == "-out=tfplan"


@pytest.mark.parametrize("bad_name", ["../evil.tfplan", "sub/../../evil", "../../etc/passwd"])
def test_path_traversal_plan_filename_is_rejected(runner, workspace, bad_name):
    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError):
            runner.plan(workspace, plan_filename=bad_name)

    mock_run.assert_not_called()


@pytest.mark.parametrize("bad_name", ["/tmp/evil.tfplan", "/etc/passwd"])
def test_absolute_plan_filename_is_rejected(runner, workspace, bad_name):
    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError):
            runner.plan(workspace, plan_filename=bad_name)

    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# No apply/destroy/arbitrary-command capability
# ---------------------------------------------------------------------------


def test_runner_has_no_apply_method():
    assert not hasattr(TerraformRunner, "apply")


def test_runner_has_no_destroy_method():
    assert not hasattr(TerraformRunner, "destroy")


@pytest.mark.parametrize(
    "forbidden",
    ["apply", "destroy", "import_", "state", "taint", "untaint", "force_unlock", "run", "execute"],
)
def test_runner_has_no_forbidden_capability(forbidden):
    assert not hasattr(TerraformRunner, forbidden)


def test_public_api_surface_is_exactly_the_allowlisted_methods():
    public_methods = {
        name
        for name, _ in inspect.getmembers(TerraformRunner, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {"fmt", "init", "validate", "plan", "show_json"}

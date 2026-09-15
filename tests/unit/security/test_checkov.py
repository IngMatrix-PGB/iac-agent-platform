"""Unit tests for the Checkov adapter.

The subprocess boundary is mocked throughout — no real `checkov` binary
is required to run this file. Real-binary behavior (including the
empirically-verified exit-code semantics this adapter relies on) is
proven separately by tests/integration/test_checkov_integration.py.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from unittest.mock import patch

import pytest

from iac_agent.domain.security import FindingSource, PolicyStatus, SecuritySeverity
from iac_agent.security import checkov as checkov_module
from iac_agent.security.checkov import (
    CheckovAdapter,
    CheckovError,
    CheckovExecutableNotFoundError,
    CheckovExecutionError,
    CheckovJsonError,
    CheckovScanProfile,
    CheckovScanResult,
    CheckovTimeoutError,
)

RUN_TARGET = "iac_agent.security.checkov.subprocess.run"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _clean_scan_json(failed_checks=None, passed=5, failed=0, skipped=0, parsing_errors=0):
    return {
        "check_type": "terraform",
        "results": {"failed_checks": failed_checks or []},
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "parsing_errors": parsing_errors,
            "resource_count": 2,
            "checkov_version": "3.3.13",
        },
    }


def _failed_check_entry(
    check_id="CKV_AWS_27", resource="module.queue.aws_sqs_queue.this", **overrides
):
    entry = {
        "check_id": check_id,
        "bc_check_id": "BC_AWS_GENERAL_16",
        "check_name": "Ensure all data stored in the SQS queue is encrypted",
        "check_result": {"result": "FAILED"},
        "code_block": None,
        "file_path": "/main.tf",
        "file_abs_path": "/private/tmp/should-never-leak/main.tf",
        "resource": resource,
        "severity": None,
        "definition_context_file_path": "/private/tmp/should-never-leak/main.tf",
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def adapter():
    return CheckovAdapter(base_env={"PATH": "/usr/bin", "HOME": "/home/test"})


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_exact_argv_is_built_correctly(adapter, workspace):
    """Batch 16.5: with no profile passed at all, `scan()` always
    performs the strict, zero-skip scan — there is no implicit
    resource-blind default skip list on the adapter itself."""
    import json as _json

    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace)

    args, kwargs = mock_run.call_args
    assert args[0] == (
        "checkov",
        "-d",
        ".",
        "--framework",
        "terraform",
        "-o",
        "json",
        "--compact",
        "--quiet",
    )


def test_empty_profile_adds_no_skip_check_flag(adapter, workspace):
    """A profile with an empty skip tuple behaves identically to no
    profile at all — never adds a bare `--skip-check` with nothing
    after it."""
    import json as _json

    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace, profile=CheckovScanProfile())

    args, _kwargs = mock_run.call_args
    assert "--skip-check" not in args[0]


def test_profile_with_skips_appends_skip_check_argv(adapter, workspace):
    """Batch 16.5: skips are applied only when the caller explicitly
    hands `scan()` a profile naming them — proving the adapter itself
    never infers which checks to skip for any resource type."""
    import json as _json

    profile = CheckovScanProfile(skipped_checks=("CKV_AWS_18", "CKV2_AWS_61"))
    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace, profile=profile)

    args, _kwargs = mock_run.call_args
    assert args[0] == (
        "checkov",
        "-d",
        ".",
        "--framework",
        "terraform",
        "-o",
        "json",
        "--compact",
        "--quiet",
        "--skip-check",
        "CKV_AWS_18,CKV2_AWS_61",
    )


def test_shell_is_never_true(adapter, workspace):
    import json as _json

    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace)

    _, kwargs = mock_run.call_args
    assert kwargs["shell"] is False


def test_workspace_passed_as_cwd_not_interpolated_into_argv(adapter, workspace):
    import json as _json

    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace)

    args, kwargs = mock_run.call_args
    assert kwargs["cwd"] == workspace
    assert str(workspace) not in args[0]


def test_nonexistent_workspace_rejected_before_execution(adapter, tmp_path):
    missing = tmp_path / "does-not-exist"

    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError, match="does not exist"):
            adapter.scan(missing)

    mock_run.assert_not_called()


def test_file_path_instead_of_directory_rejected(adapter, tmp_path):
    a_file = tmp_path / "not-a-directory.txt"
    a_file.write_text("hello")

    with patch(RUN_TARGET) as mock_run:
        with pytest.raises(ValueError, match="not a directory"):
            adapter.scan(a_file)

    mock_run.assert_not_called()


def test_configured_timeout_is_passed(workspace):
    import json as _json

    adapter = CheckovAdapter(timeout_seconds=42.0, base_env={"PATH": "/usr/bin"})
    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace)

    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 42.0


def test_missing_executable_raises_not_found_error(adapter, workspace):
    with patch(RUN_TARGET, side_effect=FileNotFoundError()):
        with pytest.raises(CheckovExecutableNotFoundError):
            adapter.scan(workspace)


def test_subprocess_timeout_raises_checkov_timeout_error(adapter, workspace):
    with patch(
        RUN_TARGET,
        side_effect=subprocess.TimeoutExpired(cmd=["checkov"], timeout=120.0),
    ):
        with pytest.raises(CheckovTimeoutError) as exc_info:
            adapter.scan(workspace)

    assert exc_info.value.timeout_seconds == 120.0


def test_true_scanner_execution_failure_raises_execution_error(adapter, workspace):
    with patch(
        RUN_TARGET,
        return_value=_completed(returncode=2, stdout="", stderr="checkov: error: bad args"),
    ):
        with pytest.raises(CheckovExecutionError):
            adapter.scan(workspace)


def test_caller_environment_is_not_leaked_into_result(workspace):
    import json as _json

    base_env = {"PATH": "/usr/bin", "HOME": "/home/super-secret-user"}
    adapter = CheckovAdapter(base_env=base_env)

    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))):
        result = adapter.scan(workspace)

    assert "super-secret-user" not in repr(result)
    for field_name in result.__dataclass_fields__:
        assert "env" not in field_name.lower()
    # base_env itself must not have been mutated by scanning.
    assert base_env == {"PATH": "/usr/bin", "HOME": "/home/super-secret-user"}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_valid_single_framework_json_parses(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert isinstance(result, CheckovScanResult)
    assert result.failed_checks == 1
    assert len(result.findings) == 1


def test_bare_summary_shape_parses_when_no_resources_found(adapter, workspace):
    import json as _json

    # Empirically observed real shape: no framework matched anything, so
    # checkov emits the summary fields directly at the top level instead
    # of wrapping them in {"results": ..., "summary": ...}.
    bare_summary = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "parsing_errors": 0,
        "resource_count": 0,
        "checkov_version": "3.3.13",
    }
    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps(bare_summary))):
        result = adapter.scan(workspace)

    assert result.passed_checks == 0
    assert result.failed_checks == 0
    assert result.findings == ()


def test_top_level_list_shape_is_explicitly_unsupported(adapter, workspace):
    """Our fixed invocation always passes --framework terraform (a single
    framework), which never produces Checkov's list-of-frameworks output
    shape in practice — so an unexpected list payload fails explicitly
    rather than being silently accepted or misread."""
    import json as _json

    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps([_clean_scan_json()]))):
        with pytest.raises(CheckovJsonError):
            adapter.scan(workspace)


def test_malformed_json_raises_checkov_json_error(adapter, workspace):
    with patch(RUN_TARGET, return_value=_completed(stdout="not json {{{")):
        with pytest.raises(CheckovJsonError):
            adapter.scan(workspace)


def test_malformed_schema_fails_explicitly(adapter, workspace):
    import json as _json

    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps({"unexpected": "shape"}))):
        with pytest.raises(CheckovJsonError):
            adapter.scan(workspace)


def test_missing_summary_and_bare_fields_fails(adapter, workspace):
    import json as _json

    payload = {"check_type": "terraform", "results": {"failed_checks": []}}
    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps(payload))):
        with pytest.raises(CheckovJsonError):
            adapter.scan(workspace)


def test_failed_check_missing_id_fails(adapter, workspace):
    import json as _json

    entry = _failed_check_entry()
    del entry["check_id"]
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)

    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        with pytest.raises(CheckovJsonError):
            adapter.scan(workspace)


def test_unknown_optional_fields_do_not_break_parsing(adapter, workspace):
    import json as _json

    entry = _failed_check_entry(some_future_field={"nested": "thing"}, another_new_key=123)
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)

    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_failed_check_has_source_checkov(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].source is FindingSource.CHECKOV


def test_failed_check_status_is_block(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].status is PolicyStatus.BLOCK


def test_block_finding_is_blocking(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].blocking is True


def test_missing_severity_defaults_to_high(adapter, workspace):
    import json as _json

    entry = _failed_check_entry(severity=None)
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].severity is SecuritySeverity.HIGH


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("LOW", SecuritySeverity.LOW),
        ("medium", SecuritySeverity.MEDIUM),
        ("High", SecuritySeverity.HIGH),
        ("CRITICAL", SecuritySeverity.CRITICAL),
        ("info", SecuritySeverity.INFO),
    ],
)
def test_supported_severity_maps_correctly(adapter, workspace, raw, expected):
    import json as _json

    entry = _failed_check_entry(severity=raw)
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].severity is expected


def test_resource_identifier_normalized_from_checkov_address(adapter, workspace):
    import json as _json

    entry = _failed_check_entry(resource="module.queue.aws_sqs_queue.this")
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert result.findings[0].resource == "module.queue.aws_sqs_queue.this"


def test_absolute_file_path_is_never_leaked(adapter, workspace):
    import json as _json

    entry = _failed_check_entry(file_abs_path="/Users/some-developer/secret-project/main.tf")
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    finding = result.findings[0]
    assert "/Users/some-developer" not in finding.message
    assert "/Users/some-developer" not in repr(finding)
    assert finding.resource is None or "/Users/some-developer" not in finding.resource


def test_full_code_block_is_never_stored(adapter, workspace):
    import json as _json

    entry = _failed_check_entry(
        code_block=[[1, 'resource "aws_sqs_queue" "x" {\n'], [2, '  name = "leaky"\n']]
    )
    payload = _clean_scan_json(failed_checks=[entry], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    finding = result.findings[0]
    assert 'resource "aws_sqs_queue"' not in finding.message
    assert 'resource "aws_sqs_queue"' not in repr(finding)


def test_no_raw_terraform_content_is_retained_on_result():
    for field_name in CheckovScanResult.__dataclass_fields__:
        assert field_name not in ("raw_json", "raw_results", "stdout", "stderr")


def test_findings_are_sorted_deterministically(adapter, workspace):
    import json as _json

    entries = [
        _failed_check_entry(check_id="CKV_AWS_99", resource="module.queue.aws_sqs_queue.z"),
        _failed_check_entry(check_id="CKV_AWS_10", resource="module.queue.aws_sqs_queue.a"),
    ]
    payload = _clean_scan_json(failed_checks=entries, passed=4, failed=2)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)

    assert [f.policy_id for f in result.findings] == ["CKV_AWS_10", "CKV_AWS_99"]


def test_reordered_equivalent_scanner_results_compare_equal(adapter, workspace):
    import json as _json

    entry_a = _failed_check_entry(check_id="CKV_AWS_10", resource="a")
    entry_b = _failed_check_entry(check_id="CKV_AWS_20", resource="b")

    payload_ab = _clean_scan_json(failed_checks=[entry_a, entry_b], passed=4, failed=2)
    payload_ba = _clean_scan_json(failed_checks=[entry_b, entry_a], passed=4, failed=2)

    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload_ab))):
        result_ab = adapter.scan(workspace)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload_ba))):
        result_ba = adapter.scan(workspace)

    assert result_ab == result_ba


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def test_passed_checks_count_is_correct(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(passed=7, failed=0, skipped=0)
    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)
    assert result.passed_checks == 7


def test_failed_checks_count_is_correct(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)
    assert result.failed_checks == 1


def test_skipped_checks_count_is_correct(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(passed=3, failed=0, skipped=2)
    with patch(RUN_TARGET, return_value=_completed(stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)
    assert result.skipped_checks == 2


def test_normalized_failed_finding_count_matches_summary_or_raises(adapter, workspace):
    import json as _json

    # summary says 2 failed, but only 1 failed_checks entry is present.
    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=2)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        with pytest.raises(CheckovExecutionError):
            adapter.scan(workspace)


# ---------------------------------------------------------------------------
# Exit-code semantics
# ---------------------------------------------------------------------------


def test_exit_one_with_findings_is_treated_as_completed_scan(adapter, workspace):
    import json as _json

    payload = _clean_scan_json(failed_checks=[_failed_check_entry()], passed=4, failed=1)
    with patch(RUN_TARGET, return_value=_completed(returncode=1, stdout=_json.dumps(payload))):
        result = adapter.scan(workspace)  # must not raise

    assert result.failed_checks == 1


def test_scanner_failure_exit_is_not_treated_as_a_finding_result(adapter, workspace):
    with patch(RUN_TARGET, return_value=_completed(returncode=2, stdout="", stderr="usage error")):
        with pytest.raises(CheckovExecutionError):
            adapter.scan(workspace)


def test_execution_failure_never_produces_a_pass_like_result(adapter, workspace):
    """A scanner crash must never be silently reinterpreted as
    "0 failed checks" — it must surface as an exception, not a result."""
    scan_result = None
    with patch(RUN_TARGET, return_value=_completed(returncode=2, stdout="", stderr="crash")):
        try:
            scan_result = adapter.scan(workspace)
        except CheckovExecutionError:
            pass

    assert scan_result is None


# ---------------------------------------------------------------------------
# API safety
# ---------------------------------------------------------------------------


def test_public_api_surface_is_exactly_scan():
    public_methods = {
        name
        for name, _ in inspect.getmembers(CheckovAdapter, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == {"scan"}


def test_module_imports_no_checkov_library_internals():
    tree = ast.parse(inspect.getsource(checkov_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"checkov", "requests", "httpx", "urllib3", "langchain", "langgraph"}
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_all_custom_exceptions_are_checkov_errors():
    for exc_cls in (
        CheckovExecutableNotFoundError,
        CheckovTimeoutError,
        CheckovExecutionError,
        CheckovJsonError,
    ):
        assert issubclass(exc_cls, CheckovError)


def test_command_never_invokes_terraform(adapter, workspace):
    import json as _json

    with patch(
        RUN_TARGET, return_value=_completed(stdout=_json.dumps(_clean_scan_json()))
    ) as mock_run:
        adapter.scan(workspace)

    args, _ = mock_run.call_args
    assert args[0][0] == "checkov"
    assert "terraform" != args[0][0]

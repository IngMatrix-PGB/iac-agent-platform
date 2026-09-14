"""Unit tests for the source-control domain model and naming/path rules
(Batches 14-15.5): `PullRequestResult`, `GitCommitIdentity`,
`derive_branch_name`, and `resolve_generated_file_path`. No HTTP, no
Git, no GitHub adapter — those are covered in
tests/unit/git/test_github.py.
"""

from __future__ import annotations

import dataclasses

import pytest

from iac_agent.domain.source_control import (
    GENERATED_FILES_ROOT,
    GitCommitIdentity,
    PullRequestResult,
    derive_branch_name,
    resolve_generated_file_path,
)

# ---------------------------------------------------------------------------
# PullRequestResult
# ---------------------------------------------------------------------------


def test_pull_request_result_fields():
    result = PullRequestResult(
        number=7,
        url="https://example.invalid/pull/7",
        branch="iac-agent/req-001",
        base_branch="main",
    )
    assert result.number == 7
    assert result.url == "https://example.invalid/pull/7"
    assert result.branch == "iac-agent/req-001"
    assert result.base_branch == "main"


def test_pull_request_result_has_no_token_or_identity_fields():
    field_names = {f.name for f in dataclasses.fields(PullRequestResult)}
    assert field_names == {"number", "url", "branch", "base_branch"}


def test_pull_request_result_is_immutable():
    result = PullRequestResult(
        number=1, url="https://example.invalid/pull/1", branch="b", base_branch="main"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.number = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# derive_branch_name
# ---------------------------------------------------------------------------


def test_derive_branch_name_valid_request_id():
    assert derive_branch_name("req-001") == "iac-agent/req-001"


def test_derive_branch_name_is_deterministic():
    assert derive_branch_name("req-001") == derive_branch_name("req-001")


def test_derive_branch_name_same_id_gives_same_branch():
    first = derive_branch_name("req-abc")
    second = derive_branch_name("req-abc")
    assert first == second


def test_derive_branch_name_different_ids_give_different_branches():
    assert derive_branch_name("req-001") != derive_branch_name("req-002")


def test_derive_branch_name_has_no_random_or_time_component():
    """Calling twice in immediate succession, or from two independent
    processes conceptually, must never differ — there is no
    uuid4()/datetime.now() anywhere in the derivation."""
    import iac_agent.domain.source_control as source_control_module

    assert "uuid" not in source_control_module.__dict__
    assert derive_branch_name("req-fixed") == "iac-agent/req-fixed"


@pytest.mark.parametrize(
    "bad_request_id",
    ["", "../escape", "/etc/passwd", "a/b", "req 001", "req~001", "req^001", "req:001", "req?001"],
)
def test_derive_branch_name_rejects_unsafe_request_id(bad_request_id):
    with pytest.raises(ValueError):
        derive_branch_name(bad_request_id)


def test_derive_branch_name_rejects_leading_hyphen():
    with pytest.raises(ValueError):
        derive_branch_name("-req-001")


# ---------------------------------------------------------------------------
# resolve_generated_file_path
# ---------------------------------------------------------------------------


def test_resolve_generated_file_path_main_tf():
    assert resolve_generated_file_path("req-001", "main.tf") == "generated/req-001/main.tf"


def test_resolve_generated_file_path_versions_tf():
    assert resolve_generated_file_path("req-001", "versions.tf") == "generated/req-001/versions.tf"


def test_resolve_generated_file_path_uses_generated_files_root_constant():
    assert resolve_generated_file_path("req-001", "main.tf").startswith(GENERATED_FILES_ROOT + "/")


def test_resolve_generated_file_path_rejects_absolute_path():
    with pytest.raises(ValueError, match="absolute"):
        resolve_generated_file_path("req-001", "/etc/passwd")


def test_resolve_generated_file_path_rejects_parent_traversal():
    with pytest.raises(ValueError, match=r"\.\."):
        resolve_generated_file_path("req-001", "../../etc/passwd")


def test_resolve_generated_file_path_rejects_nested_traversal():
    with pytest.raises(ValueError, match=r"\.\."):
        resolve_generated_file_path("req-001", "subdir/../../escape.tf")


def test_resolve_generated_file_path_rejects_empty_path():
    with pytest.raises(ValueError, match="empty"):
        resolve_generated_file_path("req-001", "")


def test_resolve_generated_file_path_rejects_backslash_path():
    with pytest.raises(ValueError):
        resolve_generated_file_path("req-001", "..\\escape.tf")


def test_resolve_generated_file_path_rejects_unsafe_request_id():
    with pytest.raises(ValueError):
        resolve_generated_file_path("../escape", "main.tf")


# ---------------------------------------------------------------------------
# GitCommitIdentity (Batch 15.5)
# ---------------------------------------------------------------------------


def test_git_commit_identity_fields():
    identity = GitCommitIdentity(name="Example Bot", email="bot@example.invalid")
    assert identity.name == "Example Bot"
    assert identity.email == "bot@example.invalid"


def test_git_commit_identity_is_immutable():
    identity = GitCommitIdentity(name="Example Bot", email="bot@example.invalid")
    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.name = "Someone Else"  # type: ignore[misc]


def test_git_commit_identity_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        GitCommitIdentity(name="", email="bot@example.invalid")


def test_git_commit_identity_rejects_empty_email():
    with pytest.raises(ValueError, match="email"):
        GitCommitIdentity(name="Example Bot", email="")


def test_git_commit_identity_rejects_email_without_at_sign():
    with pytest.raises(ValueError, match="email"):
        GitCommitIdentity(name="Example Bot", email="not-an-email")


def test_git_commit_identity_has_no_token_field():
    field_names = {f.name for f in dataclasses.fields(GitCommitIdentity)}
    assert field_names == {"name", "email"}

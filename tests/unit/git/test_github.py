"""Unit tests for the GitHub REST adapter (Batch 14).

Every test here injects a fake `HttpTransport` — there is zero real
network access, zero DNS resolution, and zero contact with
`api.github.com` anywhere in this file. `UrllibHttpTransport` (the only
production transport) is exercised only insofar as its request/response
shape is mirrored by the fakes below; it is never invoked against a
real socket here.
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest

from iac_agent.domain.source_control import GitCommitIdentity, PullRequestResult
from iac_agent.git import github as github_module
from iac_agent.git.github import (
    GitHubApiError,
    GitHubAuthenticationError,
    GitHubConflictError,
    GitHubRepository,
    GitHubResponseError,
    GitHubSourceControl,
    HttpResponse,
    HttpTransport,
)
from iac_agent.git.port import SourceControlConflictError, SourceControlError

_REPO = GitHubRepository(owner="example-user", name="iac-agent-platform")
_TOKEN = "fake-test-token-not-real"  # noqa: S105 - deliberately fake, never a real credential
_COMMIT_IDENTITY = GitCommitIdentity(name="Example Bot", email="example-bot@example.invalid")


def _json(status: int, payload: object) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(payload).encode("utf-8"))


class QueueTransport(HttpTransport):
    """Returns queued responses in call order; records every call made."""

    def __init__(self, responses: list[HttpResponse]):
        self.calls: list[dict] = []
        self._responses = list(responses)

    def request(self, *, method, url, headers, json_body=None):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "json_body": json_body}
        )
        return self._responses.pop(0)


class RaisingTransport(HttpTransport):
    def __init__(self, exc: Exception):
        self._exc = exc

    def request(self, *, method, url, headers, json_body=None):
        raise self._exc


def _happy_path_responses(*, branch_name: str, file_count: int = 2) -> list[HttpResponse]:
    blob_responses = [
        _json(201, {"sha": f"blob-sha-{i}"}) for i in range(file_count)
    ]  # one per file, in sorted-path order
    return [
        _json(404, {"message": "Not Found"}),  # branch existence check -> does not exist
        _json(200, {"object": {"sha": "base-commit-sha"}}),  # base ref
        _json(200, {"tree": {"sha": "base-tree-sha"}}),  # base commit -> tree
        *blob_responses,
        _json(201, {"sha": "new-tree-sha"}),  # tree
        _json(201, {"sha": "new-commit-sha"}),  # commit
        _json(201, {"ref": f"refs/heads/{branch_name}"}),  # create ref
        _json(201, {"number": 7, "html_url": "https://example.invalid/pull/7"}),  # pull request
    ]


# ---------------------------------------------------------------------------
# Happy path: full request sequence, URLs, headers, payload structure
# ---------------------------------------------------------------------------


def test_publish_change_happy_path_returns_pull_request_result():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001"))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    result = adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "# main\n", "versions.tf": "# versions\n"},
        commit_message="feat(iac): add SQS proposal req-001",
        pr_title="IaC proposal: req-001",
        pr_body="Request ID: req-001\n",
    )

    assert result == PullRequestResult(
        number=7,
        url="https://example.invalid/pull/7",
        branch="iac-agent/req-001",
        base_branch="main",
    )


def test_publish_change_calls_urls_scoped_to_owner_and_repo():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    for call in transport.calls:
        assert call["url"].startswith(
            "https://api.github.com/repos/example-user/iac-agent-platform"
        )


def test_publish_change_checks_branch_existence_before_any_write():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    first_call = transport.calls[0]
    assert first_call["method"] == "GET"
    assert first_call["url"].endswith("/git/ref/heads/iac-agent/req-001")


def test_publish_change_looks_up_base_ref():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    base_ref_call = transport.calls[1]
    assert base_ref_call["method"] == "GET"
    assert base_ref_call["url"].endswith("/git/ref/heads/main")


def test_publish_change_creates_one_blob_per_file():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001"))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "main content", "versions.tf": "versions content"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    blob_calls = [c for c in transport.calls if c["url"].endswith("/git/blobs")]
    assert len(blob_calls) == 2
    assert blob_calls[0]["json_body"] == {"content": "main content", "encoding": "utf-8"}
    assert blob_calls[1]["json_body"] == {"content": "versions content", "encoding": "utf-8"}


def test_publish_change_creates_tree_with_resolved_generated_paths():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001"))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x", "versions.tf": "y"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    tree_call = next(c for c in transport.calls if c["url"].endswith("/git/trees"))
    assert tree_call["json_body"]["base_tree"] == "base-tree-sha"
    paths = {entry["path"] for entry in tree_call["json_body"]["tree"]}
    assert paths == {"generated/req-001/main.tf", "generated/req-001/versions.tf"}
    for entry in tree_call["json_body"]["tree"]:
        assert entry["mode"] == "100644"
        assert entry["type"] == "blob"


def test_publish_change_creates_commit_with_message_and_parent():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="feat(iac): add SQS proposal req-001",
        pr_title="t",
        pr_body="b",
    )

    commit_call = next(c for c in transport.calls if c["url"].endswith("/git/commits"))
    assert commit_call["json_body"] == {
        "message": "feat(iac): add SQS proposal req-001",
        "tree": "new-tree-sha",
        "parents": ["base-commit-sha"],
        "author": {"name": "Example Bot", "email": "example-bot@example.invalid"},
        "committer": {"name": "Example Bot", "email": "example-bot@example.invalid"},
    }


def test_publish_change_commit_payload_uses_the_injected_identity_not_a_default():
    """A different `commit_identity` must produce a different author/
    committer payload — proving the adapter actually uses the injected
    value rather than any hardcoded or GitHub-inferred default."""
    other_identity = GitCommitIdentity(name="Someone Else", email="someone-else@example.invalid")
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=other_identity, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    commit_call = next(c for c in transport.calls if c["url"].endswith("/git/commits"))
    assert commit_call["json_body"]["author"] == {
        "name": "Someone Else",
        "email": "someone-else@example.invalid",
    }
    assert commit_call["json_body"]["committer"] == {
        "name": "Someone Else",
        "email": "someone-else@example.invalid",
    }


def test_publish_change_creates_branch_ref():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    ref_call = next(c for c in transport.calls if c["url"].endswith("/git/refs"))
    assert ref_call["method"] == "POST"
    assert ref_call["json_body"] == {"ref": "refs/heads/iac-agent/req-001", "sha": "new-commit-sha"}


def test_publish_change_creates_pull_request_with_title_head_base_body():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="IaC proposal: req-001",
        pr_body="Request ID: req-001\n",
    )

    pr_call = next(c for c in transport.calls if c["url"].endswith("/pulls"))
    assert pr_call["json_body"] == {
        "title": "IaC proposal: req-001",
        "head": "iac-agent/req-001",
        "base": "main",
        "body": "Request ID: req-001\n",
    }


def test_every_request_carries_authorization_header():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    for call in transport.calls:
        assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"


def test_every_request_carries_expected_api_version_and_accept_headers():
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    for call in transport.calls:
        assert call["headers"]["Accept"] == "application/vnd.github+json"
        assert call["headers"]["X-GitHub-Api-Version"] == "2026-03-10"
        assert call["headers"]["User-Agent"] == "iac-agent-platform"


# ---------------------------------------------------------------------------
# Branch collision
# ---------------------------------------------------------------------------


def test_existing_branch_raises_conflict_before_any_write():
    transport = QueueTransport([_json(200, {"object": {"sha": "existing-sha"}})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(SourceControlConflictError):
        adapter.publish_change(
            request_id="req-001",
            base_branch="main",
            branch_name="iac-agent/req-001",
            files={"main.tf": "x"},
            commit_message="m",
            pr_title="t",
            pr_body="b",
        )

    # Only the branch-existence check happened — no blob/tree/commit/ref
    # write was ever attempted.
    assert len(transport.calls) == 1


def test_conflict_error_is_a_source_control_conflict_error():
    transport = QueueTransport([_json(200, {"object": {"sha": "existing-sha"}})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubConflictError) as excinfo:
        adapter.publish_change(
            request_id="req-001",
            base_branch="main",
            branch_name="iac-agent/req-001",
            files={"main.tf": "x"},
            commit_message="m",
            pr_title="t",
            pr_body="b",
        )
    assert isinstance(excinfo.value, SourceControlConflictError)


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_401_403_raise_authentication_error(status):
    transport = QueueTransport([_json(status, {"message": "Bad credentials"})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubAuthenticationError):
        adapter._request_json("GET", "/git/ref/heads/main")


def test_404_on_a_required_lookup_raises_api_error():
    transport = QueueTransport([_json(404, {"message": "Not Found"})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubApiError):
        adapter._request_json("GET", "/git/commits/deadbeef")


@pytest.mark.parametrize("status", [409, 422])
def test_409_422_raise_conflict_error(status):
    transport = QueueTransport([_json(status, {"message": "Reference already exists"})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubConflictError):
        adapter._request_json("POST", "/git/refs", json_body={"ref": "x", "sha": "y"})


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_429_5xx_raise_api_error_without_retry(status):
    transport = QueueTransport([_json(status, {"message": "rate limited or server error"})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubApiError):
        adapter._request_json("GET", "/git/ref/heads/main")

    # Exactly one attempt — no automatic retry.
    assert len(transport.calls) == 1


def test_malformed_json_raises_response_error():
    transport = QueueTransport([HttpResponse(status=201, body=b"not json{{{")])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubResponseError):
        adapter._request_json("POST", "/git/blobs", json_body={"content": "x", "encoding": "utf-8"})


def test_missing_expected_field_raises_response_error():
    # Everything up to the blob call succeeds normally; the blob
    # response itself has no "sha" field at all.
    responses = _happy_path_responses(branch_name="iac-agent/req-001", file_count=1)
    responses[3] = _json(201, {"url": "https://example.invalid/blob/1"})
    transport = QueueTransport(responses)
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubResponseError):
        adapter.publish_change(
            request_id="req-001",
            base_branch="main",
            branch_name="iac-agent/req-001",
            files={"main.tf": "x"},
            commit_message="m",
            pr_title="t",
            pr_body="b",
        )


def test_transport_error_raises_source_control_error():
    transport = RaisingTransport(ConnectionError("connection refused"))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(SourceControlError):
        adapter._request_json("GET", "/git/ref/heads/main")


# ---------------------------------------------------------------------------
# Token safety
# ---------------------------------------------------------------------------


def test_token_never_appears_in_repr():
    adapter = GitHubSourceControl(
        repository=_REPO,
        token=_TOKEN,
        commit_identity=_COMMIT_IDENTITY,
        transport=QueueTransport([]),
    )
    assert _TOKEN not in repr(adapter)


def test_token_never_appears_in_a_raised_error_message():
    transport = QueueTransport([_json(401, {"message": "Bad credentials"})])
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    with pytest.raises(GitHubAuthenticationError) as excinfo:
        adapter._request_json("GET", "/git/ref/heads/main")
    assert _TOKEN not in str(excinfo.value)


def test_empty_token_is_rejected_at_construction():
    with pytest.raises(ValueError):
        GitHubSourceControl(
            repository=_REPO,
            token="",
            commit_identity=_COMMIT_IDENTITY,
            transport=QueueTransport([]),
        )


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


def test_github_adapter_does_not_import_langgraph_or_workflow_internals():
    tree = ast.parse(inspect.getsource(github_module))
    imported_roots = set()
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
            imported_modules.add(node.module)

    assert "langgraph" not in imported_roots
    forbidden_modules = {
        "iac_agent.graph.state",
        "iac_agent.execution.terraform_runner",
        "iac_agent.security.checkov",
        "iac_agent.security.gate",
    }
    assert not (imported_modules & forbidden_modules), imported_modules & forbidden_modules


def test_github_adapter_does_not_hardcode_the_real_repository():
    source = inspect.getsource(github_module)
    assert "IngMatrix-PGB" not in source


def test_github_adapter_does_not_hardcode_any_commit_identity():
    """No specific person's name/email is ever hardcoded here — every
    commit's author/committer comes only from the injected
    `GitCommitIdentity` (see the constructor and `publish_change`)."""
    source = inspect.getsource(github_module)
    for forbidden in ("IngMatrix-PGB", "Claude", "anthropic.com", "Pablo"):
        assert forbidden not in source


def test_github_adapter_generates_no_co_authored_by_trailer():
    source = inspect.getsource(github_module)
    assert "Co-authored-by" not in source
    assert "Co-Authored-By" not in source


def test_publish_change_never_omits_author_or_committer_from_commit_payload():
    """Defense-in-depth: even if a future edit forgot to thread
    `commit_identity` through, this test would fail — the commit
    payload must always carry explicit author and committer, never
    leaving GitHub to default them to the authenticated token's own
    identity."""
    transport = QueueTransport(_happy_path_responses(branch_name="iac-agent/req-001", file_count=1))
    adapter = GitHubSourceControl(
        repository=_REPO, token=_TOKEN, commit_identity=_COMMIT_IDENTITY, transport=transport
    )

    adapter.publish_change(
        request_id="req-001",
        base_branch="main",
        branch_name="iac-agent/req-001",
        files={"main.tf": "x"},
        commit_message="m",
        pr_title="t",
        pr_body="b",
    )

    commit_call = next(c for c in transport.calls if c["url"].endswith("/git/commits"))
    assert "author" in commit_call["json_body"]
    assert "committer" in commit_call["json_body"]
    assert commit_call["json_body"]["author"]["name"]
    assert commit_call["json_body"]["author"]["email"]
    assert commit_call["json_body"]["committer"]["name"]
    assert commit_call["json_body"]["committer"]["email"]

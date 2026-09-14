"""GitHub REST adapter — the only place this project knows about
GitHub's HTTP API, Git object SHAs, or authorization headers.

Implements `iac_agent.git.port.SourceControlPort` using the Git Data
API (blobs -> tree -> commit -> ref -> pull request), verified against
the current GitHub REST API documentation before implementation (see
docs/source-control.md for the exact endpoints and the verified
`X-GitHub-Api-Version` value). Uses only the Python standard library's
`urllib` for HTTP — no new runtime dependency was justified for Batch
14 (no `requests`/`httpx`, no `PyGithub`, no `git` subprocess, no `gh`
CLI).

This module never imports LangGraph, `WorkflowState`, `TerraformRunner`,
`CheckovAdapter`, or the security gate — it receives only explicit,
already-resolved source-control inputs (a repository, a token, a file
mapping, commit/PR text) and knows nothing about the workflow that
produced them.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass

from iac_agent.domain.source_control import PullRequestResult, resolve_generated_file_path
from iac_agent.git.port import SourceControlConflictError, SourceControlError

#: Verified against https://docs.github.com/en/rest/git (2026-09-13) —
#: the exact header value the current documentation's own code samples
#: use. Not copied from an older tutorial.
_API_VERSION = "2026-03-10"
_ACCEPT = "application/vnd.github+json"
_USER_AGENT = "iac-agent-platform"
_API_BASE = "https://api.github.com"

#: Requests never hang indefinitely — a stuck connection must
#: eventually fail closed (SourceControlError), never silently retry
#: or block the workflow forever.
_REQUEST_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class GitHubRepository:
    """Explicit repository identity — never hardcoded in production code.

    Batch 14 tests use generic placeholder values
    (`owner="example-user"`, `name="iac-agent-platform"`); the real
    repository identity is supplied by the caller at composition time.
    """

    owner: str
    name: str


class GitHubAuthenticationError(SourceControlError):
    """GitHub rejected the token (401) or denied the operation (403)."""


class GitHubConflictError(SourceControlConflictError):
    """GitHub reported a conflict (409/422) — most commonly, the target
    branch ref already exists."""


class GitHubApiError(SourceControlError):
    """Any other non-2xx GitHub response (404, 429, 5xx, ...)."""


class GitHubResponseError(SourceControlError):
    """A 2xx response whose body was not valid JSON, or was missing a
    field this adapter needed to read."""


@dataclass(frozen=True)
class HttpResponse:
    """A transport-agnostic HTTP response: status code plus raw body
    bytes. Never partially decoded by the transport — decoding and
    status interpretation are this adapter's job, not the transport's."""

    status: int
    body: bytes


class HttpTransport:
    """The narrow interface `GitHubSourceControl` needs from HTTP.

    Not a `typing.Protocol` here on purpose: real duck-typed fakes in
    tests just need a `request` method with this signature, and a
    concrete base class gives a single obvious place to document the
    contract. `UrllibHttpTransport` is the only production
    implementation.
    """

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        json_body: object | None = None,
    ) -> HttpResponse:
        raise NotImplementedError


class UrllibHttpTransport(HttpTransport):
    """Default `HttpTransport`, backed only by the standard library.

    A non-2xx response is still returned as an `HttpResponse` (via
    `urllib.error.HTTPError`, which carries a status code and a
    readable body) so that status-code interpretation stays entirely
    in `GitHubSourceControl` — this transport never raises for an HTTP
    error response, only for a genuine transport-level failure (DNS,
    connection refused, timeout), which becomes a `SourceControlError`.
    """

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        json_body: object | None = None,
    ) -> HttpResponse:
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return HttpResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(status=exc.code, body=exc.read())
        except urllib.error.URLError as exc:
            raise SourceControlError(
                f"network transport error contacting GitHub: {exc.reason}"
            ) from exc


def _require_field(payload: object, path: tuple[str, ...], context: str) -> object:
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise GitHubResponseError(
                f"GitHub {context} response is missing expected field {'.'.join(path)!r}"
            )
        node = node[key]
    return node


class GitHubSourceControl:
    """`SourceControlPort` implementation backed by the GitHub REST API.

    The token is received only through this constructor, stored in a
    private attribute, and never appears in `__repr__`, in any
    `PullRequestResult`, in any raised error, or anywhere else this
    adapter writes output.
    """

    def __init__(
        self,
        *,
        repository: GitHubRepository,
        token: str,
        transport: HttpTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must not be empty")
        self._repository = repository
        self._token = token
        self._transport = transport if transport is not None else UrllibHttpTransport()

    def __repr__(self) -> str:  # pragma: no cover - trivial, but excludes the token deliberately
        return f"GitHubSourceControl(repository={self._repository!r})"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/json",
        }

    def _repo_url(self, path: str) -> str:
        return f"{_API_BASE}/repos/{self._repository.owner}/{self._repository.name}{path}"

    def _send(self, method: str, path: str, *, json_body: object | None = None) -> HttpResponse:
        try:
            return self._transport.request(
                method=method,
                url=self._repo_url(path),
                headers=self._headers(),
                json_body=json_body,
            )
        except SourceControlError:
            raise
        except Exception as exc:  # noqa: BLE001 - any other transport failure is fail-closed,
            # never a silent success/retry.
            raise SourceControlError(
                f"transport error calling GitHub ({method} {path}): {type(exc).__name__}"
            ) from exc

    def _raise_for_status(self, method: str, path: str, response: HttpResponse) -> None:
        if response.status in (401, 403):
            raise GitHubAuthenticationError(
                f"GitHub authentication/authorization failed (status {response.status}) "
                f"for {method} {path}"
            )
        if response.status in (409, 422):
            raise GitHubConflictError(
                f"GitHub reported a conflict (status {response.status}) for {method} {path}"
            )
        if response.status >= 400:
            raise GitHubApiError(f"GitHub API error (status {response.status}) for {method} {path}")

    def _request_json(self, method: str, path: str, *, json_body: object | None = None) -> object:
        response = self._send(method, path, json_body=json_body)
        self._raise_for_status(method, path, response)

        if not response.body:
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubResponseError(
                f"GitHub returned malformed JSON for {method} {path}"
            ) from exc

    def _get_ref_or_none(self, ref_path: str) -> dict | None:
        """GET one ref, returning None on 404 rather than raising —
        used only to check whether a branch already exists, where a
        404 is an expected, meaningful outcome, not an error."""
        path = f"/git/ref/{ref_path}"
        response = self._send("GET", path)
        if response.status == 404:
            return None
        self._raise_for_status("GET", path, response)
        if not response.body:
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubResponseError(f"GitHub returned malformed JSON for GET {path}") from exc

    def publish_change(
        self,
        *,
        request_id: str,
        base_branch: str,
        branch_name: str,
        files: Mapping[str, str],
        commit_message: str,
        pr_title: str,
        pr_body: str,
    ) -> PullRequestResult:
        # 1. Fail closed if the target branch already exists — no
        # writes (no blobs, no tree, no commit) happen before this
        # check. This is also the structural defense against a
        # replayed publish attempt: branch naming is deterministic, so
        # a second attempt for the same request_id always collides
        # here.
        if self._get_ref_or_none(f"heads/{branch_name}") is not None:
            raise GitHubConflictError(f"branch {branch_name!r} already exists")

        # 2. Resolve the base branch's tip commit and tree.
        base_ref = self._request_json("GET", f"/git/ref/heads/{base_branch}")
        base_commit_sha = _require_field(base_ref, ("object", "sha"), "base ref")

        base_commit = self._request_json("GET", f"/git/commits/{base_commit_sha}")
        base_tree_sha = _require_field(base_commit, ("tree", "sha"), "base commit")

        # 3. One blob per file, in a deterministic (sorted) order.
        tree_entries = []
        for relative_path in sorted(files):
            blob = self._request_json(
                "POST",
                "/git/blobs",
                json_body={"content": files[relative_path], "encoding": "utf-8"},
            )
            blob_sha = _require_field(blob, ("sha",), "blob")
            tree_entries.append(
                {
                    "path": resolve_generated_file_path(request_id, relative_path),
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )

        # 4. One tree (layered on the base branch's existing tree, so
        # every other file in the repository is preserved) and one
        # commit containing every generated file together — never one
        # commit per file.
        tree = self._request_json(
            "POST", "/git/trees", json_body={"base_tree": base_tree_sha, "tree": tree_entries}
        )
        tree_sha = _require_field(tree, ("sha",), "tree")

        commit = self._request_json(
            "POST",
            "/git/commits",
            json_body={"message": commit_message, "tree": tree_sha, "parents": [base_commit_sha]},
        )
        commit_sha = _require_field(commit, ("sha",), "commit")

        # 5. Create the branch pointing at the new commit.
        self._request_json(
            "POST", "/git/refs", json_body={"ref": f"refs/heads/{branch_name}", "sha": commit_sha}
        )

        # 6. Open the pull request.
        pr = self._request_json(
            "POST",
            "/pulls",
            json_body={
                "title": pr_title,
                "head": branch_name,
                "base": base_branch,
                "body": pr_body,
            },
        )
        number = _require_field(pr, ("number",), "pull request")
        html_url = _require_field(pr, ("html_url",), "pull request")

        return PullRequestResult(
            number=number, url=html_url, branch=branch_name, base_branch=base_branch
        )

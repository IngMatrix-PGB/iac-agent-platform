"""Domain model and pure naming/path rules for source-control
publication (Batch 14).

These describe the *outcome* of publishing an approved change (a pull
request) and the deterministic conventions used to get there — branch
naming and the generated-file destination path. No HTTP, no Git object
SHAs, no GitHub-specific behavior: that lives only in
``iac_agent.git.github``. This mirrors the same separation already used
for ``derive_dlq_name`` in ``iac_agent.providers.aws.sqs.contract`` —
one canonical, pure, reusable rule, not one recomputed independently in
each caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from iac_agent.domain.workflow import validate_request_id

#: Every generated proposal branch lives under this prefix — never a
#: bare request_id, so it can never collide with an unrelated
#: human-created branch that happens to share a name.
_BRANCH_PREFIX = "iac-agent"

#: Every generated proposal's files live under this repository-relative
#: root, one subdirectory per request_id. Deliberately distinct from
#: the gitignored local `artifacts/<request_id>/` runtime workspace
#: convention (see .gitignore and iac_agent.providers.aws.sqs.renderer)
#: — that path is never source-controlled, so reusing its name here
#: would be actively misleading.
GENERATED_FILES_ROOT = "generated"

#: request_id already satisfies validate_request_id (non-empty, a
#: simple path segment, no separators, no ".."), but a Git branch name
#: segment has its own stricter safe-character rule — no spaces, and
#: only characters that can never be misread as Git ref syntax.
_BRANCH_SAFE_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class PullRequestResult:
    """The outcome of successfully publishing one approved change.

    Deliberately minimal: no raw GitHub response, no token, no
    workspace path, no HTTP status code — just enough for a caller to
    locate the pull request that was created.
    """

    number: int
    url: str
    branch: str
    base_branch: str


@dataclass(frozen=True)
class GitCommitIdentity:
    """The explicit author/committer identity for a published change's
    Git commit(s).

    Public metadata (a commit author name/email is always visible in
    the published history) — never a secret, and never the same thing
    as the GitHub token. `GitHubSourceControl` never infers this from
    whichever identity happens to own the token: every commit it
    creates states this explicitly, on purpose, so a proposal's
    authorship is never left to GitHub's own "default to the
    authenticated user" behavior.
    """

    name: str
    email: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.email or "@" not in self.email:
            raise ValueError(f"email must look like an email address, got {self.email!r}")


def derive_branch_name(request_id: str) -> str:
    """Deterministically derive the feature branch name for `request_id`.

    No timestamp, no random UUID, no caller-supplied ref syntax: the
    same `request_id` always derives the same branch name, and nothing
    else ever influences it. Raises `ValueError` for a `request_id`
    that is unsafe for `validate_request_id` (path traversal, absolute
    path, empty) or for the stricter Git-branch-segment rule (must
    start with a letter/digit; only letters, digits, `.`, `_`, `-`
    afterward — no spaces, no `~^:?*[`, no leading/trailing slash).
    """
    validate_request_id(request_id)
    if not _BRANCH_SAFE_REQUEST_ID_PATTERN.match(request_id):
        raise ValueError(
            f"request_id {request_id!r} is not safe to use in a Git branch name — "
            "it must start with a letter or digit and contain only letters, "
            "digits, '.', '_', and '-'"
        )
    return f"{_BRANCH_PREFIX}/{request_id}"


def resolve_generated_file_path(request_id: str, relative_path: str) -> str:
    """Resolve one generated file's repository-relative destination path.

    Always `generated/<request_id>/<relative_path>`. Rejects an empty,
    absolute, backslash-containing, or `..`-containing `relative_path`
    before ever building the final path — this is the one place path
    safety is enforced for every file published to source control,
    reused identically by the graph node and the GitHub adapter.
    """
    validate_request_id(request_id)
    if not relative_path:
        raise ValueError("relative_path must not be empty")
    if relative_path.startswith("/") or relative_path.startswith("\\"):
        raise ValueError(f"relative_path must not be absolute: {relative_path!r}")
    if "\\" in relative_path:
        raise ValueError(f"relative_path must use '/' separators only: {relative_path!r}")
    if ".." in relative_path.split("/"):
        raise ValueError(f"relative_path must not contain '..': {relative_path!r}")

    return f"{GENERATED_FILES_ROOT}/{request_id}/{relative_path}"

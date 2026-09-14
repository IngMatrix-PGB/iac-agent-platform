"""The source-control port: the narrow interface LangGraph depends on.

``iac_agent.graph`` knows only this ``Protocol`` — never Git object
SHAs, the GitHub blob/tree/ref APIs, HTTP status codes, or
authorization headers. It calls one high-level operation ("publish
this approved change") and gets back a `PullRequestResult` or a
`SourceControlError`. All GitHub-specific behavior lives only in the
concrete adapter, ``iac_agent.git.github``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from iac_agent.domain.source_control import PullRequestResult


class SourceControlError(Exception):
    """Base for every source-control publication failure.

    Never constructed with a token, an Authorization header value, a
    raw HTTP request/response object, or any other secret-shaped
    value — only a safe, human-readable message.
    """


class SourceControlConflictError(SourceControlError):
    """The target branch already exists.

    Phase 1 always fails closed on this: it never appends a random
    suffix, force-updates the existing branch, deletes it, or
    overwrites it. This is also the structural idempotency guard for
    a replayed/duplicated publish attempt — see docs/source-control.md.
    """


class SourceControlPort(Protocol):
    """One high-level operation: publish an already-approved change.

    Implementations receive an explicit, already-resolved file mapping
    (relative path -> text content) and explicit commit/PR text — they
    never crawl a workspace directory and never generate any of this
    content themselves.
    """

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
    ) -> PullRequestResult: ...

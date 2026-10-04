"""Bind a V3 dispatch to one pull request head and two generated blobs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from iac_agent.aws_plan.proposal import ProposalRejected
from iac_agent.aws_plan.target import REPOSITORY_FULL_NAME, REPOSITORY_ID
from iac_agent.domain.source_control import derive_branch_name, resolve_generated_file_path

_BRANCH_PREFIX = "iac-agent/"


class ShaMismatch(Exception):
    """The dispatch does not name the current head of this repository."""


@dataclass(frozen=True)
class PullRequestHead:
    number: int
    head_sha: str
    head_ref: str
    repository_id: str


class PullRequestReader(Protocol):
    def read_pull_request(self, pr_number: int) -> PullRequestHead: ...


def bind_proposal(head: PullRequestHead, *, pr_number: int, proposal_sha: str) -> str:
    if head.number != pr_number or head.head_sha != proposal_sha:
        raise ShaMismatch("proposal SHA is not the current pull request head")
    if head.repository_id != REPOSITORY_ID:
        raise ShaMismatch("pull request head is not this repository")
    if not head.head_ref.startswith(_BRANCH_PREFIX):
        raise ProposalRejected("pull request branch is not an iac-agent request branch")
    request_id = head.head_ref[len(_BRANCH_PREFIX) :]
    try:
        derived = derive_branch_name(request_id)
    except ValueError as exc:
        raise ProposalRejected("request_id is not safe for an iac-agent branch") from exc
    if derived != head.head_ref:
        raise ProposalRejected("request_id does not match the pull request branch")
    return request_id


def proposal_blob_paths(request_id: str) -> tuple[str, str]:
    return (
        resolve_generated_file_path(request_id, "main.tf"),
        resolve_generated_file_path(request_id, "versions.tf"),
    )


class GitHubPullRequestReader:
    """Read-only pull request head lookup. This is not publication authority."""

    def __init__(self, *, token: str, opener: urllib.request.OpenerDirector | None = None) -> None:
        if not token:
            raise ValueError("token must not be empty")
        self._token = token
        self._opener = opener or urllib.request.build_opener()

    def read_pull_request(self, pr_number: int) -> PullRequestHead:
        url = f"https://api.github.com/repos/{REPOSITORY_FULL_NAME}/pulls/{pr_number}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "iac-agent-aws-plan",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            raise ShaMismatch("pull request head could not be read") from exc
        if not isinstance(payload, dict):
            raise ShaMismatch("pull request head could not be read")
        try:
            head = payload["head"]
            return PullRequestHead(
                number=int(payload["number"]),
                head_sha=str(head["sha"]),
                head_ref=str(head["ref"]),
                repository_id=str(head["repo"]["id"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ShaMismatch("pull request head could not be read") from exc

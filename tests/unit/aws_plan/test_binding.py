"""Pull request head binding for a V3 dispatch."""

from __future__ import annotations

import pytest

from iac_agent.aws_plan.binding import (
    PullRequestHead,
    ShaMismatch,
    bind_proposal,
    proposal_blob_paths,
)
from iac_agent.aws_plan.proposal import ProposalRejected
from iac_agent.aws_plan.target import REPOSITORY_ID
from iac_agent.domain.source_control import derive_branch_name

_REQUEST_ID = "req-20261003T142705Z-913daf061bab"
_SHA = "a" * 40


def _head(**overrides: object) -> PullRequestHead:
    values: dict[str, object] = {
        "number": 29,
        "head_sha": _SHA,
        "head_ref": derive_branch_name(_REQUEST_ID),
        "repository_id": REPOSITORY_ID,
    }
    values.update(overrides)
    return PullRequestHead(
        number=int(values["number"]),
        head_sha=str(values["head_sha"]),
        head_ref=str(values["head_ref"]),
        repository_id=str(values["repository_id"]),
    )


def test_current_head_returns_request_id():
    request_id = bind_proposal(_head(), pr_number=29, proposal_sha=_SHA)
    assert request_id == _REQUEST_ID
    assert derive_branch_name(request_id) == f"iac-agent/{_REQUEST_ID}"


def test_moved_sha_raises_sha_mismatch():
    with pytest.raises(ShaMismatch):
        bind_proposal(_head(head_sha="b" * 40), pr_number=29, proposal_sha=_SHA)


def test_wrong_repository_raises_sha_mismatch():
    with pytest.raises(ShaMismatch):
        bind_proposal(_head(repository_id="1"), pr_number=29, proposal_sha=_SHA)


def test_fork_shape_raises_sha_mismatch():
    with pytest.raises(ShaMismatch):
        bind_proposal(_head(repository_id="999"), pr_number=29, proposal_sha=_SHA)


def test_invalid_request_id_rejected():
    with pytest.raises(ProposalRejected):
        bind_proposal(_head(head_ref="iac-agent/../etc"), pr_number=29, proposal_sha=_SHA)


def test_blob_paths_are_the_two_generated_files():
    assert proposal_blob_paths(_REQUEST_ID) == (
        f"generated/{_REQUEST_ID}/main.tf",
        f"generated/{_REQUEST_ID}/versions.tf",
    )

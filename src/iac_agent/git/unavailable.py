"""Defensive source-control port for an unconfigured publisher.

The compiled workflow requires a ``SourceControlPort``. This object stores
no credential and performs no I/O. The HTTP approve gate must return before
``resume`` when publication is absent, so normal API execution does not
call ``publish_change``.
"""

from __future__ import annotations

from collections.abc import Mapping

from iac_agent.git.port import SourceControlError


class UnavailableSourceControl:
    """Refuse publication without reading configuration or the network."""

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
    ) -> None:
        del request_id, base_branch, branch_name, files, commit_message, pr_title, pr_body
        raise SourceControlError("Source-control publishing is not configured.")

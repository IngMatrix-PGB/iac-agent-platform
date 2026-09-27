"""y/N approval-string mapping (design spec §6.5, §9). This is the
*only* place raw CLI approval text is interpreted — the result is
always a typed `ApprovalDecision`, never a raw string, before it
reaches `IacApplication.resume`."""

from __future__ import annotations

from iac_agent.domain.approval import ApprovalDecision


def parse_cli_approval(raw: str) -> ApprovalDecision:
    normalized = raw.strip().lower()
    if normalized in ("y", "yes"):
        return ApprovalDecision.APPROVE
    return ApprovalDecision.REJECT

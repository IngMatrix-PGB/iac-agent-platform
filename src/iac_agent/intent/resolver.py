"""The deterministic side of the probabilistic boundary (Batch 21).

This module owns the `ResolutionResult` discriminated union (Task 2)
and, once Task 4 lands, `ArchitectureResolver` itself — the pure,
side-effect-free function that maps a validated `ArchitectureIntent`
onto one of a closed set of existing `IacRequestSpec` targets. Nothing
in this module performs I/O, calls an LLM, or imports
`iac_agent.execution`/`iac_agent.security`/`iac_agent.git`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from iac_agent.request import IacRequestSpec


class ClarificationReason(StrEnum):
    WORKLOAD_TYPE_REQUIRED = "workload_type_required"
    INTERACTION_PATTERN_REQUIRED = "interaction_pattern_required"


@dataclass(frozen=True)
class ClarificationRequest:
    """A fully typed, resolver-authored clarification ask. The
    interpreter/LLM never invents this question — see spec §8."""

    reason: ClarificationReason
    field: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedArchitecture:
    """The architecture resolved unambiguously to an existing,
    already-validated `IacRequestSpec`. `matched_pattern` is
    observability only (e.g. `"api+synchronous+http_endpoint"`)."""

    request_spec: IacRequestSpec
    matched_pattern: str
    outcome: Literal["resolved"] = "resolved"


@dataclass(frozen=True)
class ClarificationRequired:
    """The intent is missing information in a decisive position. Never
    silently resolved — see spec §7.1's explicit `UNSPECIFIED` arms."""

    request: ClarificationRequest
    outcome: Literal["clarification_required"] = "clarification_required"


class UnsupportedReason(StrEnum):
    UNSUPPORTED_WORKLOAD = "unsupported_workload"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSUPPORTED_COMBINATION = "unsupported_combination"


@dataclass(frozen=True)
class UnsupportedArchitecture:
    """A fully specified but unsupported architecture. `detail` is a
    short, resolver-authored string — never a raw exception message or
    stack trace (see spec §8)."""

    reason: UnsupportedReason
    detail: str
    outcome: Literal["unsupported"] = "unsupported"


ResolutionResult = ResolvedArchitecture | ClarificationRequired | UnsupportedArchitecture

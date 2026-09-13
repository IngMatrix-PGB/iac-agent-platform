"""Domain models for a deterministic Terraform plan summary.

These models are provider-agnostic — they describe facts about any
Terraform plan (which resource changes what, and whether that change is
destructive), independent of SQS or any other AWS resource type. That
is why they live under ``domain/`` rather than ``providers/aws/sqs/``.

Nothing here decides security policy, severity, or pass/fail — that is
a later layer's responsibility. These models only report what
Terraform's own machine-readable plan already says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PlanAction(StrEnum):
    """A normalized classification of a Terraform resource-change action set."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"
    NO_OP = "no-op"
    READ = "read"


@dataclass(frozen=True)
class ResourceChange:
    """One resource's planned change, in a compact, review-safe form.

    Deliberately excludes the raw Terraform ``before``/``after`` value
    blobs — those can contain ARNs, generated identifiers, and other
    infrastructure detail this Phase 1 summary layer has no need to
    persist or surface by default. ``changed_fields`` exposes only the
    *names* of top-level fields that differ, never their values, and
    only when both a before and an after state genuinely exist to
    compare (never fabricated for create/delete/no-op/read).
    """

    address: str
    actions: tuple[str, ...]
    action: PlanAction
    replacement: bool
    destructive: bool
    changed_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlanSummary:
    """A deterministic summary of one Terraform plan.

    ``resource_changes`` is always sorted by address, so two logically
    equivalent plans with resource_changes listed in a different order
    produce an equal ``PlanSummary``.

    Semantics:
      - resources_to_add: addresses whose action is CREATE
      - resources_to_change: addresses whose action is UPDATE
      - resources_to_destroy: addresses whose action is DELETE or
        REPLACE (a replacement contains a destructive delete, so it is
        never also counted as a plain create)
      - NO_OP and READ actions appear in resource_changes but
        contribute to none of the three address collections above, since
        they represent no actionable infrastructure change.
    """

    resource_changes: tuple[ResourceChange, ...]
    resources_to_add: tuple[str, ...]
    resources_to_change: tuple[str, ...]
    resources_to_destroy: tuple[str, ...]
    destructive_change_detected: bool

    @property
    def add_count(self) -> int:
        return len(self.resources_to_add)

    @property
    def change_count(self) -> int:
        return len(self.resources_to_change)

    @property
    def destroy_count(self) -> int:
        return len(self.resources_to_destroy)

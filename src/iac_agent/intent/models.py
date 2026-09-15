"""The semantic contract at the platform's first probabilistic boundary
(Batch 21).

`ArchitectureIntent` is the only thing an interpreter adapter is ever
allowed to produce — never a `ResourceType`/`CompositionType`/any
existing `*Spec` (see `iac_agent.intent.resolver` for the deterministic
mapping from this semantic contract to one of those). Every field here
is either a closed, code-versioned vocabulary or a bounded primitive;
there is no `dict[str, Any]` and no unbounded string anywhere on this
model, by design (see docs/superpowers/specs/2026-09-15-structured-
architecture-intent-design.md §4 and §11.3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkloadType(StrEnum):
    API = "api"
    WORKER = "worker"
    STORAGE = "storage"
    UNSPECIFIED = "unspecified"


class InteractionPattern(StrEnum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    UNSPECIFIED = "unspecified"


class Capability(StrEnum):
    """Closed, code-versioned vocabulary. The interpreter adapter cannot
    invent a member; Pydantic rejects any string outside this enum at
    parse time (see `iac_agent.intent.port.parse_intent_payload`).

    Exactly these four members — `BACKGROUND_PROCESSING` was evaluated
    and rejected during design (no allowlist row's outcome ever depends
    on it) and must never be reintroduced.
    """

    HTTP_ENDPOINT = "http_endpoint"
    QUEUE_PROCESSING = "queue_processing"
    PERSISTENCE = "persistence"
    OBJECT_STORAGE = "object_storage"


class AwsServiceHint(StrEnum):
    """Closed vocabulary of this platform's own resource-kind words, for
    non-authoritative observability only — never read by
    `ArchitectureResolver.resolve()`. Deliberately not
    `iac_agent.domain.resource.ResourceType` reused directly, keeping
    the two enums independently versionable.
    """

    SQS = "sqs"
    S3 = "s3"
    DYNAMODB = "dynamodb"
    LAMBDA = "lambda"
    API_GATEWAY = "api_gateway"


class ArchitectureIntent(BaseModel):
    """The semantic output of the probabilistic interpreter boundary.

    `workload_type`, `interaction_pattern`, and `capabilities` are the
    only fields `ArchitectureResolver.resolve()` ever reads. Every other
    field is explanatory/advisory metadata — never authoritative over
    the resolved architecture (see `iac_agent.intent.resolver`).
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = "1"

    workload_type: WorkloadType
    interaction_pattern: InteractionPattern
    capabilities: frozenset[Capability]

    logical_name_hint: str | None = Field(default=None, max_length=128)
    user_provided_hints: tuple[AwsServiceHint, ...] = Field(default_factory=tuple, max_length=8)
    assumptions: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    unresolved_questions: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

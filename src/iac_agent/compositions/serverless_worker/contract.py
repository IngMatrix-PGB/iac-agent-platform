"""Strongly typed, deterministic serverless-worker composition contract
(Phase 2, Batch 19).

`ServerlessWorkerSpec` is the platform's first *composition* spec: it
owns one `SQSResourceSpec`, one `LambdaResourceSpec`, and one
`DynamoDBResourceSpec` plus the deterministic relationships between
them (an SQS-to-Lambda event source mapping, and Lambda-to-DynamoDB
write permissions — see
`iac_agent.compositions.serverless_worker.renderer`). It is not a
generic node/edge graph, not a YAML DAG schema, and not a
`resources: list[dict]` — the architecture itself (SQS -> Lambda ->
DynamoDB) is fixed and named (`CompositionType.SQS_LAMBDA_DYNAMODB`,
see `iac_agent.domain.composition`), and this contract's three
sub-specs are exactly the existing `SQSResourceSpec`/
`LambdaResourceSpec`/`DynamoDBResourceSpec` reused verbatim — their
field definitions are never duplicated here.

Pure domain logic: no network calls, no AWS SDK, no filesystem access,
no environment variables, no Terraform/LLM dependency. Every cross-
resource invariant below is enforced by Pydantic at construction time,
exactly like every single-resource contract in this project.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

# -- Composition name -------------------------------------------------------

_MIN_NAME_LENGTH = 1
_MAX_NAME_LENGTH = 64
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_composition_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError("name must contain only letters, digits, underscores, and hyphens")
    return value


# -- Event source mapping parameters -----------------------------------------
#
# Verified against current AWS Lambda documentation ("Lambda parameters
# for Amazon SQS event source mappings"): BatchSize defaults to 10, with
# a maximum of 10,000 for a standard queue and exactly 10 for a FIFO
# queue. MaximumBatchingWindowInSeconds defaults to 0 and is not
# supported at all for FIFO queues; for a standard queue, Lambda
# documents buffering "for up to 5 minutes" (300 seconds).

_STANDARD_QUEUE_MAX_BATCH_SIZE = 10_000
_FIFO_QUEUE_MAX_BATCH_SIZE = 10
_MIN_BATCH_SIZE = 1
_MAX_BATCHING_WINDOW_SECONDS = 300
_MIN_BATCHING_WINDOW_SECONDS = 0


class ServerlessWorkerSpec(BaseModel):
    """Canonical, validated representation of a requested SQS -> Lambda
    -> DynamoDB serverless worker architecture.

    `queue`, `function`, and `table` are exactly `SQSResourceSpec`,
    `LambdaResourceSpec`, and `DynamoDBResourceSpec` — Pydantic's own
    field typing is what enforces "the queue is really SQS, the
    function is really Lambda, the table is really DynamoDB" here;
    there is no separate `isinstance` check needed or added, and no way
    to construct this spec with a wrong-shaped nested resource at all.
    """

    composition_type: Literal["sqs_lambda_dynamodb"] = "sqs_lambda_dynamodb"
    name: str
    environment: str | None = None
    queue: SQSResourceSpec
    function: LambdaResourceSpec
    table: DynamoDBResourceSpec
    event_source_batch_size: int = 10
    event_source_maximum_batching_window_seconds: int | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_composition_name(value)

    @model_validator(mode="after")
    def _validate_identifiers_are_pairwise_distinct(self) -> ServerlessWorkerSpec:
        # "No shared-name guessing": this platform never silently
        # renames a user-supplied resource to force uniqueness. Reusing
        # the same name across the queue/function/table is a real,
        # avoidable ambiguity for anyone reviewing the generated PR (all
        # three are plainly visible together), so construction fails
        # closed here rather than producing a composition that is
        # technically valid Terraform but confusing to review.
        names = (self.queue.name, self.function.name, self.table.name)
        if len(set(names)) != len(names):
            raise ValueError(
                f"queue.name, function.name, and table.name must all be distinct (got {names!r})"
            )
        return self

    @model_validator(mode="after")
    def _validate_environment_consistency(self) -> ServerlessWorkerSpec:
        # Each sub-spec carries its own optional, metadata-only
        # `environment` field (unused by rendering/planning/policy —
        # see SQSResourceSpec/LambdaResourceSpec/DynamoDBResourceSpec).
        # When the composition itself declares an `environment`, a
        # sub-spec that also declares one must agree with it — silently
        # ignoring a contradicting sub-spec value would hide a real
        # authoring mistake rather than reject it.
        if self.environment is None:
            return self
        for label, sub_environment in (
            ("queue", self.queue.environment),
            ("function", self.function.environment),
            ("table", self.table.environment),
        ):
            if sub_environment is not None and sub_environment != self.environment:
                raise ValueError(
                    f"{label}.environment ({sub_environment!r}) does not match this "
                    f"composition's environment ({self.environment!r})"
                )
        return self

    @model_validator(mode="after")
    def _validate_event_source_batch_size(self) -> ServerlessWorkerSpec:
        max_batch_size = (
            _FIFO_QUEUE_MAX_BATCH_SIZE if self.queue.fifo else _STANDARD_QUEUE_MAX_BATCH_SIZE
        )
        if not (_MIN_BATCH_SIZE <= self.event_source_batch_size <= max_batch_size):
            raise ValueError(
                f"event_source_batch_size must be between {_MIN_BATCH_SIZE} and "
                f"{max_batch_size} for this queue (fifo={self.queue.fifo}), got "
                f"{self.event_source_batch_size}"
            )
        return self

    @model_validator(mode="after")
    def _validate_event_source_batching_window(self) -> ServerlessWorkerSpec:
        window = self.event_source_maximum_batching_window_seconds
        if window is None:
            return self
        if self.queue.fifo:
            raise ValueError(
                "event_source_maximum_batching_window_seconds is not supported for "
                "FIFO queues (verified against current AWS Lambda documentation)"
            )
        if not (_MIN_BATCHING_WINDOW_SECONDS <= window <= _MAX_BATCHING_WINDOW_SECONDS):
            raise ValueError(
                "event_source_maximum_batching_window_seconds must be between "
                f"{_MIN_BATCHING_WINDOW_SECONDS} and {_MAX_BATCHING_WINDOW_SECONDS}, got {window}"
            )
        return self

"""The shared resource-type classification (Phase 2).

A bounded, deterministic set of the AWS resource kinds this platform
supports end to end — never an arbitrary user-provided string. This is
a pure classification value: it is not stored as a field on any
resource contract (`SQSResourceSpec` already has its own pre-existing
`resource_type: Literal["sqs_queue"]` field, serialized into the
Phase 1 golden dataset, which this does not replace or duplicate).
`ResourceType` exists for the small number of places that need to
classify *which* resource a request is about — dispatch, PR/commit
text, eval field expectations — without hand-rolling `isinstance`
checks in each of them.
"""

from __future__ import annotations

from enum import StrEnum


class ResourceType(StrEnum):
    SQS = "sqs"
    S3 = "s3"

"""The composition dispatch boundary (Batch 19) — the composition
counterpart to `iac_agent.providers.aws.resource`.

`CompositionSpec` is a plain typed union (currently a union of one
member) — not a generic `dict[str, Any]`, not a plugin registry.
`composition_type_of` is the single explicit dispatch used wherever
code needs to classify which architecture a composition spec is,
mirroring `resource_type_of` exactly.
"""

from __future__ import annotations

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.composition import CompositionType

CompositionSpec = ServerlessWorkerSpec


def composition_type_of(spec: CompositionSpec) -> CompositionType:
    """Classify a validated composition spec by its `CompositionType`.

    Raises `ValueError` for any spec type this platform does not
    support — never silently defaults to
    `CompositionType.SQS_LAMBDA_DYNAMODB`.
    """
    match spec:
        case ServerlessWorkerSpec():
            return CompositionType.SQS_LAMBDA_DYNAMODB
    raise ValueError(f"unsupported composition spec type: {type(spec).__name__}")

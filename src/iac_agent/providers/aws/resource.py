"""The shared AWS resource dispatch boundary (Phase 2).

The one place that knows every AWS resource contract exists side by
side. `AWSResourceSpec` is a plain typed union — not a generic
`dict[str, Any]`, not a plugin registry, not a metaprogrammed schema.
`resource_type_of` is the single explicit dispatch used wherever code
needs to classify which kind of resource a spec is (PR/commit text,
eval field expectations) without hand-rolling `isinstance` checks in
each call site.

Adding a new resource type means adding one member to `ResourceType`,
one arm to `AWSResourceSpec`, and one `case` here — not a new
abstraction layer.
"""

from __future__ import annotations

from iac_agent.domain.resource import ResourceType
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

AWSResourceSpec = (
    SQSResourceSpec
    | S3ResourceSpec
    | DynamoDBResourceSpec
    | LambdaResourceSpec
    | ApiGatewayResourceSpec
)


def resource_type_of(spec: AWSResourceSpec) -> ResourceType:
    """Classify a validated resource spec by its `ResourceType`.

    Raises `ValueError` for any spec type this platform does not
    support — never silently defaults to `ResourceType.SQS`.
    """
    match spec:
        case SQSResourceSpec():
            return ResourceType.SQS
        case S3ResourceSpec():
            return ResourceType.S3
        case DynamoDBResourceSpec():
            return ResourceType.DYNAMODB
        case LambdaResourceSpec():
            return ResourceType.LAMBDA
        case ApiGatewayResourceSpec():
            return ResourceType.API_GATEWAY
    raise ValueError(f"unsupported resource spec type: {type(spec).__name__}")

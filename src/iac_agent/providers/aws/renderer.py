"""Shared Terraform composition renderer dispatch (Phase 2).

`AWSResourceRenderer` is the one place that knows all concrete
renderers (SQS, S3, DynamoDB, Lambda) exist side by side. The graph
depends only on this — never directly on
`TerraformCompositionRenderer`, `S3TerraformCompositionRenderer`,
`DynamoDBTerraformCompositionRenderer`, or
`LambdaTerraformCompositionRenderer`. A plain explicit `match`,
appropriate for a small, bounded set of supported resource types — not
a plugin framework, and an unsupported spec type fails closed rather
than silently defaulting to SQS.
"""

from __future__ import annotations

from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.dynamodb.renderer import DynamoDBTerraformCompositionRenderer
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.lambda_function.renderer import LambdaTerraformCompositionRenderer
from iac_agent.providers.aws.resource import AWSResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import S3TerraformCompositionRenderer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition


class AWSResourceRenderer:
    """Dispatches `render(spec, ...)` to the resource-specific renderer.

    Holds no state beyond the concrete renderers it wraps (all of which
    are themselves stateless) — safe to construct once and reuse.
    """

    def __init__(
        self,
        *,
        sqs_renderer: TerraformCompositionRenderer | None = None,
        s3_renderer: S3TerraformCompositionRenderer | None = None,
        dynamodb_renderer: DynamoDBTerraformCompositionRenderer | None = None,
        lambda_renderer: LambdaTerraformCompositionRenderer | None = None,
    ) -> None:
        self._sqs_renderer = (
            sqs_renderer if sqs_renderer is not None else TerraformCompositionRenderer()
        )
        self._s3_renderer = (
            s3_renderer if s3_renderer is not None else S3TerraformCompositionRenderer()
        )
        self._dynamodb_renderer = (
            dynamodb_renderer
            if dynamodb_renderer is not None
            else DynamoDBTerraformCompositionRenderer()
        )
        self._lambda_renderer = (
            lambda_renderer if lambda_renderer is not None else LambdaTerraformCompositionRenderer()
        )

    def render(self, spec: AWSResourceSpec, *, module_source: str) -> GeneratedTerraformComposition:
        match spec:
            case SQSResourceSpec():
                return self._sqs_renderer.render(spec, module_source=module_source)
            case S3ResourceSpec():
                return self._s3_renderer.render(spec, module_source=module_source)
            case DynamoDBResourceSpec():
                return self._dynamodb_renderer.render(spec, module_source=module_source)
            case LambdaResourceSpec():
                return self._lambda_renderer.render(spec, module_source=module_source)
        raise ValueError(f"unsupported resource spec type: {type(spec).__name__}")

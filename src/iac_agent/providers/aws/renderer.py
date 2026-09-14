"""Shared Terraform composition renderer dispatch (Phase 2).

`AWSResourceRenderer` is the one place that knows both concrete
renderers (SQS, S3) exist side by side. The graph depends only on this
— never directly on `TerraformCompositionRenderer` or
`S3TerraformCompositionRenderer`. A plain two-case `match`, appropriate
for exactly two supported resource types — not a plugin framework, and
an unsupported spec type fails closed rather than silently defaulting
to SQS.
"""

from __future__ import annotations

from iac_agent.providers.aws.resource import AWSResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import S3TerraformCompositionRenderer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition


class AWSResourceRenderer:
    """Dispatches `render(spec, ...)` to the resource-specific renderer.

    Holds no state beyond the two concrete renderers it wraps (both of
    which are themselves stateless) — safe to construct once and reuse.
    """

    def __init__(
        self,
        *,
        sqs_renderer: TerraformCompositionRenderer | None = None,
        s3_renderer: S3TerraformCompositionRenderer | None = None,
    ) -> None:
        self._sqs_renderer = (
            sqs_renderer if sqs_renderer is not None else TerraformCompositionRenderer()
        )
        self._s3_renderer = (
            s3_renderer if s3_renderer is not None else S3TerraformCompositionRenderer()
        )

    def render(self, spec: AWSResourceSpec, *, module_source: str) -> GeneratedTerraformComposition:
        match spec:
            case SQSResourceSpec():
                return self._sqs_renderer.render(spec, module_source=module_source)
            case S3ResourceSpec():
                return self._s3_renderer.render(spec, module_source=module_source)
        raise ValueError(f"unsupported resource spec type: {type(spec).__name__}")

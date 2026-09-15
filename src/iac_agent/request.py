"""The request-level dispatch boundary between single-AWS-resource
requests and multi-resource composition requests (Phase 2, Batch 19).

Before Batch 19, `iac_agent.graph.workflow` assumed every request was
exactly one `AWSResourceSpec` — the graph, `AWSResourceRenderer`,
`evaluate_platform_policies`, `checkov_profile_for`, and
`evaluate_security_gate` all dispatched on a single `ResourceType`.
`IacRequestSpec` widens "what a request can be" to also include a
`ServerlessWorkerSpec` (`iac_agent.compositions.serverless_worker`)
without touching `AWSResourceSpec`/`AWSResourceRenderer` themselves —
see `iac_agent.graph.workflow` for how each graph node now branches on
the request kind.

`IacRenderer` is this module's own request-level rendering dispatch —
"Conceptually: `IacRenderer.render(spec)` dispatching:
`AWSResourceSpec -> AWSResourceRenderer`,
`ServerlessWorkerSpec -> ServerlessWorkerTerraformRenderer`" — kept as
a thin wrapper that computes each concrete renderer's own expected
module-source shape from the same `trusted_module_dirs` mapping every
resource type already had. `AWSResourceRenderer` itself needed no
change at all: this module only computes `module_source`/
`module_sources` and forwards to whichever concrete renderer applies.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda.renderer import (
    ApiLambdaModuleSources,
    ApiLambdaTerraformRenderer,
)
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.compositions.serverless_worker.renderer import (
    ServerlessWorkerModuleSources,
    ServerlessWorkerTerraformRenderer,
)
from iac_agent.domain.resource import ResourceType
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.resource import AWSResourceSpec, resource_type_of
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition

IacRequestSpec = AWSResourceSpec | ServerlessWorkerSpec | ApiLambdaSpec


class IacRenderer:
    """Dispatches `render(spec, ...)` to the AWS-resource renderer or
    the serverless-worker composition renderer.

    Holds no state beyond the two renderers it wraps (both themselves
    stateless) — safe to construct once and reuse.
    """

    def __init__(
        self,
        *,
        aws_renderer: AWSResourceRenderer | None = None,
        serverless_worker_renderer: ServerlessWorkerTerraformRenderer | None = None,
        api_lambda_renderer: ApiLambdaTerraformRenderer | None = None,
    ) -> None:
        self._aws_renderer = aws_renderer if aws_renderer is not None else AWSResourceRenderer()
        self._serverless_worker_renderer = (
            serverless_worker_renderer
            if serverless_worker_renderer is not None
            else ServerlessWorkerTerraformRenderer()
        )
        self._api_lambda_renderer = (
            api_lambda_renderer if api_lambda_renderer is not None else ApiLambdaTerraformRenderer()
        )

    def render(
        self,
        spec: IacRequestSpec,
        *,
        trusted_module_dirs: Mapping[ResourceType, Path],
        workspace: Path,
    ) -> GeneratedTerraformComposition:
        """Render `spec` into a deterministic Terraform composition.

        `trusted_module_dirs` is the same `ResourceType`-keyed mapping
        every AWS resource type already uses — neither
        `ServerlessWorkerSpec` nor `ApiLambdaSpec` needs a separate
        `CompositionType`-keyed mapping at all, because their
        constituent sub-resources (SQS/Lambda/DynamoDB, API Gateway/
        Lambda) are already registered there; this method just
        resolves the ones each composition needs relative to
        `workspace` at once instead of one at a time.
        """
        match spec:
            case ServerlessWorkerSpec():
                module_sources = ServerlessWorkerModuleSources(
                    queue=os.path.relpath(trusted_module_dirs[ResourceType.SQS], start=workspace),
                    function=os.path.relpath(
                        trusted_module_dirs[ResourceType.LAMBDA], start=workspace
                    ),
                    table=os.path.relpath(
                        trusted_module_dirs[ResourceType.DYNAMODB], start=workspace
                    ),
                )
                return self._serverless_worker_renderer.render(spec, module_sources=module_sources)
            case ApiLambdaSpec():
                api_module_sources = ApiLambdaModuleSources(
                    api=os.path.relpath(
                        trusted_module_dirs[ResourceType.API_GATEWAY], start=workspace
                    ),
                    function=os.path.relpath(
                        trusted_module_dirs[ResourceType.LAMBDA], start=workspace
                    ),
                )
                return self._api_lambda_renderer.render(spec, module_sources=api_module_sources)
            case _:
                module_source = os.path.relpath(
                    trusted_module_dirs[resource_type_of(spec)], start=workspace
                )
                return self._aws_renderer.render(spec, module_source=module_source)

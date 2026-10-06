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

from collections.abc import Mapping
from pathlib import Path

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda.renderer import (
    ApiLambdaModuleSources,
    ApiLambdaTerraformRenderer,
)
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.api_lambda_dynamodb.renderer import (
    ApiLambdaDynamoDbModuleSources,
    ApiLambdaDynamoDbTerraformRenderer,
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

#: Generated Terraform is committed at ``generated/<request_id>/``, two
#: levels below the repository root, so every module ``source`` points
#: at the repository's own trusted modules from there. It never depends
#: on where the runtime workspace lives.
PUBLISHED_MODULE_SOURCE_PREFIX = "../../terraform/modules"


def _published_module_source(module_dir: Path) -> str:
    return f"{PUBLISHED_MODULE_SOURCE_PREFIX}/{module_dir.name}"


IacRequestSpec = AWSResourceSpec | ServerlessWorkerSpec | ApiLambdaSpec | ApiLambdaDynamoDbSpec


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
        api_lambda_dynamodb_renderer: ApiLambdaDynamoDbTerraformRenderer | None = None,
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
        self._api_lambda_dynamodb_renderer = (
            api_lambda_dynamodb_renderer
            if api_lambda_dynamodb_renderer is not None
            else ApiLambdaDynamoDbTerraformRenderer()
        )

    def render(
        self,
        spec: IacRequestSpec,
        *,
        trusted_module_dirs: Mapping[ResourceType, Path],
    ) -> GeneratedTerraformComposition:
        """Render `spec` into a deterministic Terraform composition.

        `trusted_module_dirs` is the same `ResourceType`-keyed mapping
        every AWS resource type already uses — neither
        `ServerlessWorkerSpec` nor `ApiLambdaSpec` needs a separate
        `CompositionType`-keyed mapping at all, because their
        constituent sub-resources (SQS/Lambda/DynamoDB, API Gateway/
        Lambda) are already registered there; this method just
        resolves the ones each composition needs at once instead of one
        at a time. Each resolves to its published source,
        `../../terraform/modules/<module>`; the workflow lays out the
        runtime workspace so that same text also resolves at plan time.
        """
        match spec:
            case ServerlessWorkerSpec():
                module_sources = ServerlessWorkerModuleSources(
                    queue=_published_module_source(trusted_module_dirs[ResourceType.SQS]),
                    function=_published_module_source(trusted_module_dirs[ResourceType.LAMBDA]),
                    table=_published_module_source(trusted_module_dirs[ResourceType.DYNAMODB]),
                )
                return self._serverless_worker_renderer.render(spec, module_sources=module_sources)
            case ApiLambdaDynamoDbSpec():
                # Checked before ApiLambdaSpec() only for readability —
                # the two are structurally distinct types, so match's
                # isinstance semantics make ordering irrelevant to
                # correctness here (see compositions/resource.py).
                api_lambda_dynamodb_module_sources = ApiLambdaDynamoDbModuleSources(
                    api=_published_module_source(trusted_module_dirs[ResourceType.API_GATEWAY]),
                    function=_published_module_source(trusted_module_dirs[ResourceType.LAMBDA]),
                    table=_published_module_source(trusted_module_dirs[ResourceType.DYNAMODB]),
                )
                return self._api_lambda_dynamodb_renderer.render(
                    spec, module_sources=api_lambda_dynamodb_module_sources
                )
            case ApiLambdaSpec():
                api_module_sources = ApiLambdaModuleSources(
                    api=_published_module_source(trusted_module_dirs[ResourceType.API_GATEWAY]),
                    function=_published_module_source(trusted_module_dirs[ResourceType.LAMBDA]),
                )
                return self._api_lambda_renderer.render(spec, module_sources=api_module_sources)
            case _:
                module_source = _published_module_source(
                    trusted_module_dirs[resource_type_of(spec)]
                )
                return self._aws_renderer.render(spec, module_source=module_source)

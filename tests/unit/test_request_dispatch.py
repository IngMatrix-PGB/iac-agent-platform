"""Unit tests for the request-level rendering dispatch boundary (Batch 19).

Mirrors tests/unit/providers/aws/test_renderer_dispatch.py's discipline:
proves `IacRenderer` dispatches an `AWSResourceSpec` to
`AWSResourceRenderer` and a `ServerlessWorkerSpec` to
`ServerlessWorkerTerraformRenderer`, computing the right module-source
shape for each from the same `trusted_module_dirs` mapping.
"""

from __future__ import annotations

from pathlib import Path

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.compositions.serverless_worker.renderer import ServerlessWorkerModuleSources
from iac_agent.domain.resource import ResourceType
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.request import IacRenderer


class _FakeAWSResourceRenderer:
    def __init__(self):
        self.calls: list[tuple] = []

    def render(self, spec, *, module_source):
        self.calls.append((spec, module_source))
        return "aws-rendered"


class _FakeServerlessWorkerRenderer:
    def __init__(self):
        self.calls: list[tuple] = []

    def render(self, spec, *, module_sources):
        self.calls.append((spec, module_sources))
        return "composition-rendered"


_TRUSTED_MODULE_DIRS = {
    ResourceType.SQS: Path("/repo/terraform/modules/sqs"),
    ResourceType.S3: Path("/repo/terraform/modules/s3"),
    ResourceType.DYNAMODB: Path("/repo/terraform/modules/dynamodb"),
    ResourceType.LAMBDA: Path("/repo/terraform/modules/lambda"),
}


def test_aws_resource_spec_dispatches_to_the_aws_renderer():
    fake_aws = _FakeAWSResourceRenderer()
    fake_composition = _FakeServerlessWorkerRenderer()
    renderer = IacRenderer(aws_renderer=fake_aws, serverless_worker_renderer=fake_composition)

    spec = SQSResourceSpec(name="orders-queue")
    workspace = Path("/repo/artifacts/req-1")

    result = renderer.render(spec, trusted_module_dirs=_TRUSTED_MODULE_DIRS, workspace=workspace)

    assert result == "aws-rendered"
    assert len(fake_aws.calls) == 1
    assert fake_composition.calls == []
    called_spec, module_source = fake_aws.calls[0]
    assert called_spec is spec
    assert module_source == "../../terraform/modules/sqs"


def test_serverless_worker_spec_dispatches_to_the_composition_renderer():
    fake_aws = _FakeAWSResourceRenderer()
    fake_composition = _FakeServerlessWorkerRenderer()
    renderer = IacRenderer(aws_renderer=fake_aws, serverless_worker_renderer=fake_composition)

    spec = ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )
    workspace = Path("/repo/artifacts/req-2")

    result = renderer.render(spec, trusted_module_dirs=_TRUSTED_MODULE_DIRS, workspace=workspace)

    assert result == "composition-rendered"
    assert fake_aws.calls == []
    assert len(fake_composition.calls) == 1
    called_spec, module_sources = fake_composition.calls[0]
    assert called_spec is spec
    assert module_sources == ServerlessWorkerModuleSources(
        queue="../../terraform/modules/sqs",
        function="../../terraform/modules/lambda",
        table="../../terraform/modules/dynamodb",
    )


def test_default_construction_builds_real_renderers():
    # No fakes injected — proves the default-construction path works
    # (both concrete renderers are cheap, stateless, real objects).
    renderer = IacRenderer()
    assert renderer is not None

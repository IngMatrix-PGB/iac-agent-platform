"""Unit tests for the shared AWS resource renderer dispatch (Phase 2)."""

from __future__ import annotations

import pytest

from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


class _RecordingRenderer:
    def __init__(self):
        self.calls: list[dict] = []

    def render(self, spec, *, module_source):
        self.calls.append({"spec": spec, "module_source": module_source})
        return "rendered"


def _dispatcher(**overrides):
    defaults = {
        "sqs_renderer": _RecordingRenderer(),
        "s3_renderer": _RecordingRenderer(),
        "dynamodb_renderer": _RecordingRenderer(),
        "lambda_renderer": _RecordingRenderer(),
    }
    defaults.update(overrides)
    return AWSResourceRenderer(**defaults), defaults


def test_sqs_spec_dispatches_to_sqs_renderer():
    dispatcher, renderers = _dispatcher()

    spec = SQSResourceSpec(name="order-events")
    result = dispatcher.render(spec, module_source="../../terraform/modules/sqs")

    assert result == "rendered"
    assert len(renderers["sqs_renderer"].calls) == 1
    assert renderers["sqs_renderer"].calls[0]["spec"] is spec
    assert renderers["s3_renderer"].calls == []
    assert renderers["dynamodb_renderer"].calls == []
    assert renderers["lambda_renderer"].calls == []


def test_s3_spec_dispatches_to_s3_renderer():
    dispatcher, renderers = _dispatcher()

    spec = S3ResourceSpec(name="my-example-bucket")
    result = dispatcher.render(spec, module_source="../../terraform/modules/s3")

    assert result == "rendered"
    assert len(renderers["s3_renderer"].calls) == 1
    assert renderers["s3_renderer"].calls[0]["spec"] is spec
    assert renderers["sqs_renderer"].calls == []
    assert renderers["dynamodb_renderer"].calls == []
    assert renderers["lambda_renderer"].calls == []


def test_dynamodb_spec_dispatches_to_dynamodb_renderer():
    dispatcher, renderers = _dispatcher()

    spec = DynamoDBResourceSpec(
        name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    )
    result = dispatcher.render(spec, module_source="../../terraform/modules/dynamodb")

    assert result == "rendered"
    assert len(renderers["dynamodb_renderer"].calls) == 1
    assert renderers["dynamodb_renderer"].calls[0]["spec"] is spec
    assert renderers["sqs_renderer"].calls == []
    assert renderers["s3_renderer"].calls == []
    assert renderers["lambda_renderer"].calls == []


def test_lambda_spec_dispatches_to_lambda_renderer():
    dispatcher, renderers = _dispatcher()

    spec = LambdaResourceSpec(name="orders-processor", handler="app.handler")
    result = dispatcher.render(spec, module_source="../../terraform/modules/lambda")

    assert result == "rendered"
    assert len(renderers["lambda_renderer"].calls) == 1
    assert renderers["lambda_renderer"].calls[0]["spec"] is spec
    assert renderers["sqs_renderer"].calls == []
    assert renderers["s3_renderer"].calls == []
    assert renderers["dynamodb_renderer"].calls == []


def test_unsupported_spec_type_fails_closed_never_defaults_to_sqs():
    dispatcher, renderers = _dispatcher()

    with pytest.raises(ValueError, match="unsupported resource spec type"):
        dispatcher.render(object(), module_source="x")  # type: ignore[arg-type]

    assert renderers["sqs_renderer"].calls == []
    assert renderers["s3_renderer"].calls == []
    assert renderers["dynamodb_renderer"].calls == []
    assert renderers["lambda_renderer"].calls == []


def test_default_construction_uses_real_renderers():
    dispatcher = AWSResourceRenderer()
    spec = SQSResourceSpec(name="order-events")
    composition = dispatcher.render(spec, module_source="../../terraform/modules/sqs")
    assert "main.tf" in composition.files

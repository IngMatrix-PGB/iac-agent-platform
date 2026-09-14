"""Unit tests for the shared AWS resource renderer dispatch (Phase 2)."""

from __future__ import annotations

import pytest

from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


class _RecordingRenderer:
    def __init__(self):
        self.calls: list[dict] = []

    def render(self, spec, *, module_source):
        self.calls.append({"spec": spec, "module_source": module_source})
        return "rendered"


def test_sqs_spec_dispatches_to_sqs_renderer():
    sqs_renderer = _RecordingRenderer()
    s3_renderer = _RecordingRenderer()
    dispatcher = AWSResourceRenderer(sqs_renderer=sqs_renderer, s3_renderer=s3_renderer)

    spec = SQSResourceSpec(name="order-events")
    result = dispatcher.render(spec, module_source="../../terraform/modules/sqs")

    assert result == "rendered"
    assert len(sqs_renderer.calls) == 1
    assert sqs_renderer.calls[0]["spec"] is spec
    assert s3_renderer.calls == []


def test_s3_spec_dispatches_to_s3_renderer():
    sqs_renderer = _RecordingRenderer()
    s3_renderer = _RecordingRenderer()
    dispatcher = AWSResourceRenderer(sqs_renderer=sqs_renderer, s3_renderer=s3_renderer)

    spec = S3ResourceSpec(name="my-example-bucket")
    result = dispatcher.render(spec, module_source="../../terraform/modules/s3")

    assert result == "rendered"
    assert len(s3_renderer.calls) == 1
    assert s3_renderer.calls[0]["spec"] is spec
    assert sqs_renderer.calls == []


def test_unsupported_spec_type_fails_closed_never_defaults_to_sqs():
    sqs_renderer = _RecordingRenderer()
    dispatcher = AWSResourceRenderer(sqs_renderer=sqs_renderer, s3_renderer=_RecordingRenderer())

    with pytest.raises(ValueError, match="unsupported resource spec type"):
        dispatcher.render(object(), module_source="x")  # type: ignore[arg-type]

    assert sqs_renderer.calls == []


def test_default_construction_uses_real_renderers():
    dispatcher = AWSResourceRenderer()
    spec = SQSResourceSpec(name="order-events")
    composition = dispatcher.render(spec, module_source="../../terraform/modules/sqs")
    assert "main.tf" in composition.files

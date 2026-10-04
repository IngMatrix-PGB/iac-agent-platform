"""Canonical SQS proposal bytes must round-trip through the existing renderer."""

from __future__ import annotations

import pytest

from iac_agent.aws_plan.proposal import ProposalRejected, decode_sqs_proposal
from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

RENDERER = TerraformCompositionRenderer()


def _files(spec: SQSResourceSpec) -> tuple[str, str]:
    rendered = RENDERER.render(spec)
    return rendered.files["main.tf"], rendered.files["versions.tf"]


def _replace_value(main_tf: str, attribute_prefix: str, new_value: str) -> str:
    lines = []
    replaced = False
    for line in main_tf.splitlines(keepends=True):
        if not replaced and line.startswith(attribute_prefix):
            lines.append(f"{attribute_prefix}{new_value}\n")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        raise AssertionError(f"attribute not found: {attribute_prefix!r}")
    return "".join(lines)


def test_renderer_output_decodes_to_same_spec():
    specs = [
        SQSResourceSpec(name="order-events"),
        SQSResourceSpec(
            name="order-events",
            encryption=EncryptionSpec(kms_key_id="alias/aws/sqs"),
        ),
        SQSResourceSpec(name="order-processing.fifo", fifo=True),
        SQSResourceSpec(name="order-events", dlq=DlqSpec(enabled=False, max_receive_count=None)),
        SQSResourceSpec(
            name="order-events",
            tags={"ManagedBy": "iac-agent-platform", "Purpose": "phase1-live-smoke"},
        ),
    ]
    for spec in specs:
        main_tf, versions_tf = _files(spec)
        decoded = decode_sqs_proposal(main_tf, versions_tf)
        assert decoded == SQSResourceSpec(
            name=spec.name,
            fifo=spec.fifo,
            visibility_timeout_seconds=spec.visibility_timeout_seconds,
            message_retention_seconds=spec.message_retention_seconds,
            delay_seconds=spec.delay_seconds,
            encryption=spec.encryption,
            dlq=spec.dlq,
            tags=spec.tags,
        )
        assert decoded.environment is None


def test_versions_mismatch_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    with pytest.raises(ProposalRejected):
        decode_sqs_proposal(main_tf, versions_tf + "\n")


def test_function_call_value_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    mutated = _replace_value(main_tf, "  delay_seconds              = ", "max(1, 2)")
    with pytest.raises(ProposalRejected):
        decode_sqs_proposal(mutated, versions_tf)


def test_file_and_templatefile_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    for value in ('file("x")', 'templatefile("x", {})'):
        mutated = _replace_value(main_tf, "  name                       = ", value)
        with pytest.raises(ProposalRejected):
            decode_sqs_proposal(mutated, versions_tf)


def test_references_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    for value in (
        "local.x",
        "var.x",
        "data.aws_caller_identity.current.account_id",
        "aws_sqs_queue.q.id",
    ):
        mutated = _replace_value(main_tf, "  name                       = ", value)
        with pytest.raises(ProposalRejected):
            decode_sqs_proposal(mutated, versions_tf)


def test_unescaped_interpolation_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    mutated = _replace_value(main_tf, "  name                       = ", '"${var.x}"')
    with pytest.raises(ProposalRejected):
        decode_sqs_proposal(mutated, versions_tf)


def test_reordered_attribute_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    name_line = '  name                       = "order-events"\n'
    fifo_line = "  fifo                       = false\n"
    swapped = main_tf.replace(name_line + fifo_line, fifo_line + name_line, 1)
    assert swapped != main_tf
    with pytest.raises(ProposalRejected):
        decode_sqs_proposal(swapped, versions_tf)


def test_wrong_module_source_rejected():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events"))
    mutated = main_tf.replace("../../terraform/modules/sqs", "../../terraform/modules/s3", 1)
    with pytest.raises(ProposalRejected):
        decode_sqs_proposal(mutated, versions_tf)


def test_environment_is_not_recovered():
    main_tf, versions_tf = _files(SQSResourceSpec(name="order-events", environment="staging"))
    decoded = decode_sqs_proposal(main_tf, versions_tf)
    assert decoded.environment is None
    assert decoded.name == "order-events"

"""Unit tests for the serverless-worker Terraform composition renderer
(Phase 2, Batch 19).

Covers `ServerlessWorkerTerraformRenderer`'s string output directly —
structural content (module blocks, the event source mapping, the two
composition-owned IAM policies, environment-variable/tag merging) and
determinism. Real `terraform fmt`/`init`/`validate`/`plan` proof lives
in `tests/integration/test_serverless_worker_renderer_terraform.py`,
not here — this suite never shells out to any binary.
"""

from __future__ import annotations

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.compositions.serverless_worker.renderer import (
    ServerlessWorkerModuleSources,
    ServerlessWorkerTerraformRenderer,
)
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

_SOURCES = ServerlessWorkerModuleSources(
    queue="../../terraform/modules/sqs",
    function="../../terraform/modules/lambda",
    table="../../terraform/modules/dynamodb",
)


def _spec(**overrides) -> ServerlessWorkerSpec:
    defaults = {
        "name": "orders-worker",
        "queue": SQSResourceSpec(name="orders-queue"),
        "function": LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        "table": DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    }
    defaults.update(overrides)
    return ServerlessWorkerSpec(**defaults)


def _render(spec: ServerlessWorkerSpec) -> str:
    composition = ServerlessWorkerTerraformRenderer().render(spec, module_sources=_SOURCES)
    return composition.files["main.tf"]


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_output_is_exactly_main_tf_and_versions_tf():
    composition = ServerlessWorkerTerraformRenderer().render(_spec(), module_sources=_SOURCES)
    assert set(composition.files) == {"main.tf", "versions.tf"}


def test_never_emits_a_raw_single_resource_block():
    main_tf = _render(_spec())
    for forbidden in (
        'resource "aws_sqs_queue"',
        'resource "aws_lambda_function"',
        'resource "aws_iam_role"',
        'resource "aws_dynamodb_table"',
        'resource "aws_cloudwatch_log_group"',
    ):
        assert forbidden not in main_tf


def test_instantiates_exactly_the_three_trusted_modules():
    main_tf = _render(_spec())
    assert 'module "queue" {' in main_tf
    assert 'module "function" {' in main_tf
    assert 'module "table" {' in main_tf
    assert main_tf.count(f'source = "{_SOURCES.queue}"') == 1
    assert main_tf.count(f'source = "{_SOURCES.function}"') == 1
    assert main_tf.count(f'source = "{_SOURCES.table}"') == 1


# ---------------------------------------------------------------------------
# Module attribute pass-through
# ---------------------------------------------------------------------------


def test_queue_module_reflects_the_spec():
    main_tf = _render(_spec(queue=SQSResourceSpec(name="custom-queue", fifo=False)))
    assert 'name                       = "custom-queue"' in main_tf


def test_function_module_reflects_the_spec():
    main_tf = _render(
        _spec(function=LambdaResourceSpec(name="custom-fn", handler="pkg.mod.handler"))
    )
    assert 'name                 = "custom-fn"' in main_tf
    assert 'handler              = "pkg.mod.handler"' in main_tf


def test_table_module_reflects_the_spec():
    main_tf = _render(
        _spec(
            table=DynamoDBResourceSpec(
                name="custom-table", partition_key=DynamoDBKeySpec(name="id", type="N")
            )
        )
    )
    assert 'name                   = "custom-table"' in main_tf
    assert 'hash_key_type          = "N"' in main_tf


# ---------------------------------------------------------------------------
# Environment-variable injection
# ---------------------------------------------------------------------------


def test_environment_variables_merge_expression_references_module_outputs():
    main_tf = _render(_spec())
    assert "environment_variables = merge(" in main_tf
    assert "QUEUE_URL  = module.queue.queue_url" in main_tf
    assert "TABLE_NAME = module.table.table_name" in main_tf


def test_user_supplied_environment_variables_are_included_in_the_merge():
    spec = _spec(
        function=LambdaResourceSpec(
            name="orders-processor",
            handler="app.handler",
            environment_variables={"LOG_LEVEL": "INFO"},
        )
    )
    main_tf = _render(spec)
    assert '"LOG_LEVEL" = "INFO"' in main_tf
    assert "QUEUE_URL" in main_tf
    assert "TABLE_NAME" in main_tf


# ---------------------------------------------------------------------------
# Tag merging
# ---------------------------------------------------------------------------


def test_empty_composition_and_sub_spec_tags_render_as_plain_empty_map():
    main_tf = _render(_spec())
    # The function module always renders `tags` isolated (unpadded,
    # since it follows the always-isolated `environment_variables`
    # line); the queue/table modules render it padded into their own
    # attribute-alignment group instead — both are still a plain `{}`,
    # never a `tags = merge(...)` call, whenever every tag source is
    # empty (unlike `environment_variables`, which always uses merge()
    # regardless).
    assert "tags = merge(" not in main_tf
    assert main_tf.count("= {}") == 3


def test_composition_tags_alone_are_applied_to_every_module():
    main_tf = _render(_spec(tags={"Owner": "platform"}))
    assert main_tf.count('"Owner" = "platform"') == 3


def test_sub_spec_tags_override_composition_tags_on_key_collision():
    spec = _spec(
        tags={"Team": "platform"},
        queue=SQSResourceSpec(name="orders-queue", tags={"Team": "orders"}),
    )
    main_tf = _render(spec)
    queue_block = main_tf.split('module "queue"')[1].split('module "table"')[0]
    assert '"Team" = "orders"' in queue_block
    assert '"Team" = "platform"' not in queue_block
    # function/table have no tags of their own, so the composition's
    # "Team" = "platform" tag legitimately still applies to them.
    function_block = main_tf.split('module "function"')[1]
    assert '"Team" = "platform"' in function_block


# ---------------------------------------------------------------------------
# Event source mapping
# ---------------------------------------------------------------------------


def test_event_source_mapping_binds_queue_to_function():
    main_tf = _render(_spec())
    assert 'resource "aws_lambda_event_source_mapping" "queue_to_function" {' in main_tf
    assert "event_source_arn = module.queue.queue_arn" in main_tf
    assert "function_name    = module.function.function_name" in main_tf
    assert "enabled          = true" in main_tf


def test_event_source_mapping_uses_the_configured_batch_size():
    main_tf = _render(_spec(event_source_batch_size=250))
    assert "batch_size" in main_tf
    assert "250" in main_tf


def test_batching_window_omitted_when_not_configured():
    main_tf = _render(_spec())
    assert "maximum_batching_window_in_seconds" not in main_tf


def test_batching_window_present_when_configured():
    main_tf = _render(_spec(event_source_maximum_batching_window_seconds=30))
    assert "maximum_batching_window_in_seconds = 30" in main_tf


# ---------------------------------------------------------------------------
# IAM relationship resources
# ---------------------------------------------------------------------------


def test_sqs_consumer_policy_grants_exactly_the_three_documented_actions():
    main_tf = _render(_spec())
    assert '"sqs:ReceiveMessage"' in main_tf
    assert '"sqs:DeleteMessage"' in main_tf
    assert '"sqs:GetQueueAttributes"' in main_tf
    assert "sqs:ChangeMessageVisibility" not in main_tf
    assert "sqs:*" not in main_tf


def test_sqs_consumer_policy_is_scoped_to_the_queue_arn():
    main_tf = _render(_spec())
    assert "resources = [module.queue.queue_arn]" in main_tf


def test_dynamodb_write_policy_grants_exactly_put_item():
    main_tf = _render(_spec())
    assert '"dynamodb:PutItem"' in main_tf
    assert "dynamodb:Scan" not in main_tf
    assert "dynamodb:Query" not in main_tf
    assert "dynamodb:BatchWriteItem" not in main_tf
    assert "dynamodb:DeleteItem" not in main_tf
    assert "dynamodb:UpdateItem" not in main_tf
    assert "dynamodb:*" not in main_tf


def test_dynamodb_write_policy_is_scoped_to_the_table_arn():
    main_tf = _render(_spec())
    assert "resources = [module.table.table_arn]" in main_tf


def test_both_composition_iam_policies_attach_to_the_function_execution_role():
    main_tf = _render(_spec())
    assert main_tf.count("role   = module.function.execution_role_name") == 2


def test_iam_policy_names_are_derived_from_the_composition_name():
    main_tf = _render(_spec(name="checkout-worker"))
    assert '"checkout-worker-sqs-consumer"' in main_tf
    assert '"checkout-worker-dynamodb-write"' in main_tf


def test_no_wildcard_action_or_resource_anywhere():
    main_tf = _render(_spec())
    assert '"*"' not in main_tf
    assert "iam:*" not in main_tf


def test_no_managed_policy_attachment_or_raw_iam_role():
    main_tf = _render(_spec())
    assert "policy_attachment" not in main_tf
    assert 'resource "aws_iam_role"' not in main_tf


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_the_same_spec_twice_is_byte_identical():
    spec = _spec()
    first = ServerlessWorkerTerraformRenderer().render(spec, module_sources=_SOURCES)
    second = ServerlessWorkerTerraformRenderer().render(spec, module_sources=_SOURCES)
    assert first.files == second.files

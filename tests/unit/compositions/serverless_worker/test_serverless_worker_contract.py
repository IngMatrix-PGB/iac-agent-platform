"""Unit tests for the serverless-worker composition contract (Phase 2,
Batch 19).

Covers `ServerlessWorkerSpec`: valid construction/defaults, every
cross-resource invariant, and boundary values for the event-source
mapping parameters. No network, filesystem, LLM, or Terraform
dependency is exercised anywhere in this module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


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


# ---------------------------------------------------------------------------
# Valid cases / defaults
# ---------------------------------------------------------------------------


def test_composition_with_all_defaults():
    spec = _spec()

    assert spec.composition_type == "sqs_lambda_dynamodb"
    assert spec.name == "orders-worker"
    assert spec.environment is None
    assert isinstance(spec.queue, SQSResourceSpec)
    assert isinstance(spec.function, LambdaResourceSpec)
    assert isinstance(spec.table, DynamoDBResourceSpec)
    assert spec.event_source_batch_size == 10
    assert spec.event_source_maximum_batching_window_seconds is None
    assert spec.tags == {}


def test_sub_specs_are_reused_verbatim_not_duplicated():
    queue = SQSResourceSpec(name="orders-queue", visibility_timeout_seconds=90)
    function = LambdaResourceSpec(
        name="orders-processor", handler="app.handler", memory_size_mb=512
    )
    table = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type="S"),
        deletion_protection=False,
    )
    spec = _spec(queue=queue, function=function, table=table)

    assert spec.queue.visibility_timeout_seconds == 90
    assert spec.function.memory_size_mb == 512
    assert spec.table.deletion_protection is False


def test_composition_with_custom_tags():
    spec = _spec(tags={"Owner": "platform"})
    assert spec.tags == {"Owner": "platform"}


def test_composition_with_environment_set_and_consistent_sub_specs():
    spec = _spec(
        environment="staging",
        queue=SQSResourceSpec(name="orders-queue", environment="staging"),
    )
    assert spec.environment == "staging"
    assert spec.queue.environment == "staging"


def test_composition_with_custom_event_source_parameters():
    spec = _spec(event_source_batch_size=50, event_source_maximum_batching_window_seconds=30)
    assert spec.event_source_batch_size == 50
    assert spec.event_source_maximum_batching_window_seconds == 30


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="")


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="a" * 65)


def test_name_with_invalid_character_is_rejected():
    with pytest.raises(ValidationError):
        _spec(name="orders worker")


# ---------------------------------------------------------------------------
# Cross-resource type invariants (structurally enforced by Pydantic typing)
# ---------------------------------------------------------------------------


def test_queue_field_rejects_a_value_sqs_itself_would_reject():
    # fifo=True requires the name to end with ".fifo" — SQSResourceSpec's
    # own invariant, exercised here through the nested field to prove
    # `queue` really is a full SQSResourceSpec, not a loosely typed dict.
    with pytest.raises(ValidationError):
        _spec(queue={"name": "orders-queue", "fifo": True})


def test_function_field_requires_a_handler():
    with pytest.raises(ValidationError):
        _spec(function={"name": "orders-processor"})


def test_table_field_requires_a_partition_key():
    with pytest.raises(ValidationError):
        _spec(table={"name": "orders-table"})


# ---------------------------------------------------------------------------
# No duplicate generated logical identifiers
# ---------------------------------------------------------------------------


def test_duplicate_queue_and_function_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            queue=SQSResourceSpec(name="orders"),
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
        )


def test_duplicate_queue_and_table_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            queue=SQSResourceSpec(name="orders"),
            table=DynamoDBResourceSpec(
                name="orders", partition_key=DynamoDBKeySpec(name="pk", type="S")
            ),
        )


def test_duplicate_function_and_table_names_are_rejected():
    with pytest.raises(ValidationError):
        _spec(
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
            table=DynamoDBResourceSpec(
                name="orders", partition_key=DynamoDBKeySpec(name="pk", type="S")
            ),
        )


def test_all_three_names_identical_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            queue=SQSResourceSpec(name="orders"),
            function=LambdaResourceSpec(name="orders", handler="app.handler"),
            table=DynamoDBResourceSpec(
                name="orders", partition_key=DynamoDBKeySpec(name="pk", type="S")
            ),
        )


# ---------------------------------------------------------------------------
# Environment consistency
# ---------------------------------------------------------------------------


def test_environment_mismatch_with_queue_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            queue=SQSResourceSpec(name="orders-queue", environment="production"),
        )


def test_environment_mismatch_with_function_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            function=LambdaResourceSpec(
                name="orders-processor", handler="app.handler", environment="production"
            ),
        )


def test_environment_mismatch_with_table_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            environment="staging",
            table=DynamoDBResourceSpec(
                name="orders-table",
                partition_key=DynamoDBKeySpec(name="pk", type="S"),
                environment="production",
            ),
        )


def test_sub_spec_environment_is_ignored_when_composition_environment_is_unset():
    # No contradiction check applies at all when the composition itself
    # never declares an environment.
    spec = _spec(queue=SQSResourceSpec(name="orders-queue", environment="production"))
    assert spec.environment is None
    assert spec.queue.environment == "production"


# ---------------------------------------------------------------------------
# Event source batch size
# ---------------------------------------------------------------------------


def test_standard_queue_batch_size_minimum_and_maximum():
    assert _spec(event_source_batch_size=1).event_source_batch_size == 1
    assert _spec(event_source_batch_size=10_000).event_source_batch_size == 10_000


def test_standard_queue_batch_size_above_maximum_is_rejected():
    with pytest.raises(ValidationError):
        _spec(event_source_batch_size=10_001)


def test_batch_size_zero_is_rejected():
    with pytest.raises(ValidationError):
        _spec(event_source_batch_size=0)


def test_fifo_queue_batch_size_maximum_is_ten():
    spec = _spec(
        queue=SQSResourceSpec(name="orders-queue.fifo", fifo=True), event_source_batch_size=10
    )
    assert spec.event_source_batch_size == 10


def test_fifo_queue_batch_size_above_ten_is_rejected():
    with pytest.raises(ValidationError):
        _spec(
            queue=SQSResourceSpec(name="orders-queue.fifo", fifo=True),
            event_source_batch_size=11,
        )


# ---------------------------------------------------------------------------
# Event source maximum batching window
# ---------------------------------------------------------------------------


def test_batching_window_minimum_and_maximum():
    minimum = _spec(event_source_maximum_batching_window_seconds=0)
    maximum = _spec(event_source_maximum_batching_window_seconds=300)
    assert minimum.event_source_maximum_batching_window_seconds == 0
    assert maximum.event_source_maximum_batching_window_seconds == 300


def test_batching_window_above_maximum_is_rejected():
    with pytest.raises(ValidationError):
        _spec(event_source_maximum_batching_window_seconds=301)


def test_batching_window_negative_is_rejected():
    with pytest.raises(ValidationError):
        _spec(event_source_maximum_batching_window_seconds=-1)


def test_batching_window_is_rejected_for_fifo_queues():
    with pytest.raises(ValidationError):
        _spec(
            queue=SQSResourceSpec(name="orders-queue.fifo", fifo=True),
            event_source_batch_size=10,
            event_source_maximum_batching_window_seconds=5,
        )


def test_batching_window_omitted_is_valid_for_fifo_queues():
    spec = _spec(
        queue=SQSResourceSpec(name="orders-queue.fifo", fifo=True), event_source_batch_size=10
    )
    assert spec.event_source_maximum_batching_window_seconds is None


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_constructing_the_same_input_twice_is_deterministic():
    first = _spec()
    second = _spec()
    assert first == second

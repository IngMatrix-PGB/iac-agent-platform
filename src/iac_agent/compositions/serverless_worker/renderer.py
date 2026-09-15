"""Deterministic Terraform composition renderer for the SQS -> Lambda ->
DynamoDB serverless-worker architecture (Phase 2, Batch 19).

Converts a validated `ServerlessWorkerSpec` into a small, self-
contained root Terraform composition that instantiates the three
already-existing trusted modules (`terraform/modules/sqs`,
`terraform/modules/lambda`, `terraform/modules/dynamodb`) side by side
and binds them together with exactly two kinds of composition-owned
relationship resources:

  - `aws_lambda_event_source_mapping` — the SQS -> Lambda trigger, not
    owned by either trusted module (it names both a queue and a
    function, so it does not belong inside either one alone).
  - two narrowly-scoped `aws_iam_role_policy` resources, granting the
    Lambda execution role (exposed by the trusted Lambda module's own
    `execution_role_name` output — Batch 19's only Lambda-module
    change) exactly the SQS-consumer and DynamoDB-write permissions
    this specific architecture needs, each scoped to the one queue/
    table ARN involved. This is "Option B" from Batch 19's IAM design
    evaluation: the trusted Lambda module's own baseline behavior (its
    CloudWatch Logs permissions) is completely unchanged, permissions
    stay deterministic (derived only from the composition's own typed
    relationships, never from arbitrary caller-supplied actions/
    resources), and the Lambda module itself never becomes generic IAM
    machinery aware of SQS or DynamoDB.

This module never emits a raw `aws_sqs_queue`, `aws_lambda_function`,
`aws_iam_role`, or `aws_dynamodb_table` resource block — those remain
exclusively owned by the trusted modules. No network calls, no
filesystem I/O, no subprocess execution. The same validated spec always
renders to byte-identical output.

Reuses the shared, resource-agnostic HCL-rendering primitives from
`iac_agent.providers.aws.terraform_render` exactly as every other
renderer in this project does.
"""

from __future__ import annotations

from dataclasses import dataclass

from iac_agent.providers.aws.terraform_render import (
    GeneratedTerraformComposition,
    hcl_bool,
    hcl_number,
    hcl_optional_number,
    hcl_optional_string,
    hcl_string,
    hcl_tags,
    render_provider_block,
    render_versions_tf,
)

from .contract import ServerlessWorkerSpec

#: The exact three CloudWatch-Logs-style AWS-managed-policy actions
#: `AWSLambdaSQSQueueExecutionRole` grants (verified directly against
#: that managed policy's own published JSON document — see
#: docs/compositions/serverless-worker.md) — reused here as an inline,
#: queue-ARN-scoped policy instead of attaching the managed policy
#: itself (which is unconditionally `Resource: "*"` and also grants the
#: CloudWatch Logs actions the trusted Lambda module already grants on
#: its own). `sqs:ChangeMessageVisibility` is deliberately excluded: it
#: is not part of the AWS-documented required permission set for a
#: standard SQS event source mapping.
_SQS_CONSUMER_ACTIONS = ("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes")

#: Batch 19 supports exactly one DynamoDB write interaction — PutItem.
#: `UpdateItem`/`Scan`/`Query`/`BatchWriteItem`/`DeleteItem` are all
#: explicit non-goals (see docs/compositions/serverless-worker.md).
_DYNAMODB_WRITE_ACTIONS = ("dynamodb:PutItem",)

#: The two non-secret environment variables Batch 19 injects into the
#: function — a Terraform reference to each constituent module's own
#: output, never a hardcoded/guessed value.
_QUEUE_URL_ENV_VAR = "QUEUE_URL"
_TABLE_NAME_ENV_VAR = "TABLE_NAME"


@dataclass(frozen=True)
class ServerlessWorkerModuleSources:
    """The three trusted-module `source` values this composition needs.

    A plain, explicit trio — not a `dict[str, str]` — so a caller can
    never accidentally supply a source for a module this composition
    doesn't have (or misspell a dict key silently).
    """

    queue: str
    function: str
    table: str


def _module_attr_line(key: str, value: str, width: int) -> str:
    return f"  {key.ljust(width)} = {value}\n"


def _isolated_attr_line(key: str, value: str) -> str:
    # Mirrors the existing single-resource renderers' treatment of a
    # multi-line-valued attribute (a non-empty tags map, or here also
    # the environment_variables merge() expression): never forced into
    # the surrounding attributes' `terraform fmt` alignment group,
    # rendered with exactly one space around `=` instead.
    return f"  {key} = {value}\n"


def _merged_tags_hcl(composition_tags: dict[str, str], sub_tags: dict[str, str]) -> str:
    """Render this module's `tags` argument as the composition's own
    shared tags merged with this specific resource's own tags (the
    sub-resource's own tag wins on a key collision — Python's own dict-
    update precedence, matching what `terraform`'s `merge()` would also
    do, applied here rather than deferred to a runtime `merge()` call).

    Both maps are plain Python string->string values known at render
    time — unlike the environment-variables case below, nothing here
    depends on an unresolved Terraform reference, so this can (and,
    to keep the rendered HCL a plain literal map rather than a nested
    function call, should) be merged directly in Python.
    """
    return hcl_tags({**composition_tags, **sub_tags})


_QUEUE_MODULE_KEYS = (
    "name",
    "fifo",
    "visibility_timeout_seconds",
    "message_retention_seconds",
    "delay_seconds",
    "kms_key_id",
    "dlq_enabled",
    "max_receive_count",
)
_QUEUE_MODULE_WIDTH = max(len(key) for key in _QUEUE_MODULE_KEYS)

_TABLE_MODULE_KEYS = (
    "name",
    "hash_key_name",
    "hash_key_type",
    "range_key_name",
    "range_key_type",
    "point_in_time_recovery",
    "deletion_protection",
)
_TABLE_MODULE_WIDTH = max(len(key) for key in _TABLE_MODULE_KEYS)

_FUNCTION_MODULE_KEYS = (
    "name",
    "handler",
    "runtime",
    "architecture",
    "memory_size_mb",
    "timeout_seconds",
    "reserved_concurrency",
    "tracing_mode",
    "log_retention_days",
)
_FUNCTION_MODULE_WIDTH = max(len(key) for key in _FUNCTION_MODULE_KEYS)


def _render_queue_module_block(spec: ServerlessWorkerSpec, source: str) -> str:
    queue = spec.queue
    tags_hcl = _merged_tags_hcl(spec.tags, queue.tags)
    tags_line = (
        _module_attr_line("tags", tags_hcl, _QUEUE_MODULE_WIDTH)
        if "\n" not in tags_hcl
        else _isolated_attr_line("tags", tags_hcl)
    )
    return (
        'module "queue" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(queue.name), _QUEUE_MODULE_WIDTH)
        + _module_attr_line("fifo", hcl_bool(queue.fifo), _QUEUE_MODULE_WIDTH)
        + _module_attr_line(
            "visibility_timeout_seconds",
            hcl_number(queue.visibility_timeout_seconds),
            _QUEUE_MODULE_WIDTH,
        )
        + _module_attr_line(
            "message_retention_seconds",
            hcl_number(queue.message_retention_seconds),
            _QUEUE_MODULE_WIDTH,
        )
        + _module_attr_line("delay_seconds", hcl_number(queue.delay_seconds), _QUEUE_MODULE_WIDTH)
        + _module_attr_line(
            "kms_key_id", hcl_optional_string(queue.encryption.kms_key_id), _QUEUE_MODULE_WIDTH
        )
        + _module_attr_line("dlq_enabled", hcl_bool(queue.dlq.enabled), _QUEUE_MODULE_WIDTH)
        + _module_attr_line(
            "max_receive_count",
            hcl_optional_number(queue.dlq.max_receive_count),
            _QUEUE_MODULE_WIDTH,
        )
        + tags_line
        + "}\n"
    )


def _render_table_module_block(spec: ServerlessWorkerSpec, source: str) -> str:
    table = spec.table
    sort_key_name = table.sort_key.name if table.sort_key is not None else None
    sort_key_type = table.sort_key.type.value if table.sort_key is not None else None
    tags_hcl = _merged_tags_hcl(spec.tags, table.tags)
    tags_line = (
        _module_attr_line("tags", tags_hcl, _TABLE_MODULE_WIDTH)
        if "\n" not in tags_hcl
        else _isolated_attr_line("tags", tags_hcl)
    )
    return (
        'module "table" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(table.name), _TABLE_MODULE_WIDTH)
        + _module_attr_line(
            "hash_key_name", hcl_string(table.partition_key.name), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "hash_key_type", hcl_string(table.partition_key.type.value), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "range_key_name", hcl_optional_string(sort_key_name), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "range_key_type", hcl_optional_string(sort_key_type), _TABLE_MODULE_WIDTH
        )
        + _module_attr_line(
            "point_in_time_recovery",
            hcl_bool(table.point_in_time_recovery),
            _TABLE_MODULE_WIDTH,
        )
        + _module_attr_line(
            "deletion_protection", hcl_bool(table.deletion_protection), _TABLE_MODULE_WIDTH
        )
        + tags_line
        + "}\n"
    )


def _render_environment_variables_expr(spec: ServerlessWorkerSpec) -> str:
    """Build the `environment_variables` value as
    `merge(<user-supplied literal map>, <QUEUE_URL/TABLE_NAME module
    references>)`.

    Unlike the tags case above, `QUEUE_URL`/`TABLE_NAME` are genuine
    Terraform-only-known references (each constituent module's own
    output) — they cannot be resolved in Python, so this is the one
    place in this renderer that must emit a real `merge()` call rather
    than a precomputed literal map. Each argument is rendered on its
    own line (the canonical multi-line function-call form `terraform
    fmt` produces for a call whose arguments don't fit inline) —
    verified against a real `terraform fmt -check -diff` run, since a
    single-line-per-argument nesting was not already fmt-clean.
    """
    user_map_hcl = _nested_inline_map(spec.function.environment_variables, indent=4)

    width = max(len(_QUEUE_URL_ENV_VAR), len(_TABLE_NAME_ENV_VAR))
    reserved_block = (
        "{\n"
        f"      {_QUEUE_URL_ENV_VAR.ljust(width)} = module.queue.queue_url\n"
        f"      {_TABLE_NAME_ENV_VAR.ljust(width)} = module.table.table_name\n"
        "    }"
    )
    return f"merge(\n    {user_map_hcl},\n    {reserved_block}\n  )"


def _nested_inline_map(items: dict[str, str], *, indent: int) -> str:
    """Render a plain string->string map as an inline object nested
    `indent` spaces deep inside a multi-line function call — unlike
    `hcl_tags` (which assumes it sits directly after a top-level
    `key = ` attribute), the closing brace here must land at exactly
    `indent` spaces to match the opening brace's own line, with entries
    two spaces deeper — verified against a real `terraform fmt -check
    -diff` run.
    """
    if not items:
        return "{}"
    sorted_items = sorted(items.items())
    quoted_keys = [hcl_string(key) for key, _ in sorted_items]
    width = max(len(quoted_key) for quoted_key in quoted_keys)
    entry_indent = " " * (indent + 2)
    body = "\n".join(
        f"{entry_indent}{quoted_key.ljust(width)} = {hcl_string(value)}"
        for quoted_key, (_, value) in zip(quoted_keys, sorted_items, strict=True)
    )
    close_indent = " " * indent
    return f"{{\n{body}\n{close_indent}}}"


def _render_function_module_block(spec: ServerlessWorkerSpec, source: str) -> str:
    function = spec.function
    tags_hcl = _merged_tags_hcl(spec.tags, function.tags)
    # Unlike the queue/table module blocks, `tags` here always follows
    # `environment_variables`, which is itself always rendered isolated
    # (a merge() expression) — that permanently breaks the preceding
    # attributes' alignment group, so `tags` can never rejoin it either,
    # regardless of whether its own value happens to be single-line.
    # Verified against a real `terraform fmt -check -diff` run.
    tags_line = _isolated_attr_line("tags", tags_hcl)
    return (
        'module "function" {\n'
        f"  source = {hcl_string(source)}\n\n"
        + _module_attr_line("name", hcl_string(function.name), _FUNCTION_MODULE_WIDTH)
        + _module_attr_line("handler", hcl_string(function.handler), _FUNCTION_MODULE_WIDTH)
        + _module_attr_line("runtime", hcl_string(function.runtime.value), _FUNCTION_MODULE_WIDTH)
        + _module_attr_line(
            "architecture", hcl_string(function.architecture.value), _FUNCTION_MODULE_WIDTH
        )
        + _module_attr_line(
            "memory_size_mb", hcl_number(function.memory_size_mb), _FUNCTION_MODULE_WIDTH
        )
        + _module_attr_line(
            "timeout_seconds", hcl_number(function.timeout_seconds), _FUNCTION_MODULE_WIDTH
        )
        + _module_attr_line(
            "reserved_concurrency",
            hcl_optional_number(function.reserved_concurrency),
            _FUNCTION_MODULE_WIDTH,
        )
        + _module_attr_line(
            "tracing_mode", hcl_string(function.tracing_mode.value), _FUNCTION_MODULE_WIDTH
        )
        + _module_attr_line(
            "log_retention_days",
            hcl_number(function.log_retention_days),
            _FUNCTION_MODULE_WIDTH,
        )
        + _isolated_attr_line("environment_variables", _render_environment_variables_expr(spec))
        + tags_line
        + "}\n"
    )


def _render_event_source_mapping_block(spec: ServerlessWorkerSpec) -> str:
    has_window = spec.event_source_maximum_batching_window_seconds is not None
    attrs: list[tuple[str, str]] = [
        ("event_source_arn", "module.queue.queue_arn"),
        ("function_name", "module.function.function_name"),
        ("batch_size", hcl_number(spec.event_source_batch_size)),
        ("enabled", "true"),
    ]
    if has_window:
        attrs.append(
            (
                "maximum_batching_window_in_seconds",
                hcl_number(spec.event_source_maximum_batching_window_seconds),
            )
        )
    # All attributes here are single-line scalars, so — unlike the
    # module blocks above — they are always one contiguous `terraform
    # fmt` alignment group; the width is simply the widest key actually
    # present (the optional window attribute widens the group only when
    # it is actually rendered).
    width = max(len(key) for key, _ in attrs)
    body = "".join(_module_attr_line(key, value, width) for key, value in attrs)
    return f'resource "aws_lambda_event_source_mapping" "queue_to_function" {{\n{body}}}\n'


def _render_sqs_consumer_policy_block(spec: ServerlessWorkerSpec) -> str:
    actions_hcl = ",\n".join(f'      "{action}"' for action in _SQS_CONSUMER_ACTIONS)
    return (
        'data "aws_iam_policy_document" "sqs_consumer" {\n'
        "  statement {\n"
        '    effect = "Allow"\n'
        "    actions = [\n"
        f"{actions_hcl},\n"
        "    ]\n"
        "    resources = [module.queue.queue_arn]\n"
        "  }\n"
        "}\n"
        "\n"
        'resource "aws_iam_role_policy" "sqs_consumer" {\n'
        f"  name   = {hcl_string(f'{spec.name}-sqs-consumer')}\n"
        "  role   = module.function.execution_role_name\n"
        "  policy = data.aws_iam_policy_document.sqs_consumer.json\n"
        "}\n"
    )


def _render_dynamodb_write_policy_block(spec: ServerlessWorkerSpec) -> str:
    actions_hcl = ",\n".join(f'      "{action}"' for action in _DYNAMODB_WRITE_ACTIONS)
    return (
        'data "aws_iam_policy_document" "dynamodb_write" {\n'
        "  statement {\n"
        '    effect = "Allow"\n'
        "    actions = [\n"
        f"{actions_hcl},\n"
        "    ]\n"
        "    resources = [module.table.table_arn]\n"
        "  }\n"
        "}\n"
        "\n"
        'resource "aws_iam_role_policy" "dynamodb_write" {\n'
        f"  name   = {hcl_string(f'{spec.name}-dynamodb-write')}\n"
        "  role   = module.function.execution_role_name\n"
        "  policy = data.aws_iam_policy_document.dynamodb_write.json\n"
        "}\n"
    )


def _render_main_tf(
    spec: ServerlessWorkerSpec, module_sources: ServerlessWorkerModuleSources
) -> str:
    return (
        "# GENERATED FILE — do not edit by hand.\n"
        "# Produced deterministically by ServerlessWorkerTerraformRenderer from a\n"
        "# validated ServerlessWorkerSpec. Regenerate instead of modifying.\n\n"
        + render_provider_block()
        + "\n"
        + _render_queue_module_block(spec, module_sources.queue)
        + "\n"
        + _render_table_module_block(spec, module_sources.table)
        + "\n"
        + _render_function_module_block(spec, module_sources.function)
        + "\n"
        + _render_event_source_mapping_block(spec)
        + "\n"
        + _render_sqs_consumer_policy_block(spec)
        + "\n"
        + _render_dynamodb_write_policy_block(spec)
    )


class ServerlessWorkerTerraformRenderer:
    """Renders a validated `ServerlessWorkerSpec` into a root Terraform
    composition instantiating the trusted SQS, DynamoDB, and Lambda
    modules plus the relationship resources that bind them.

    Holds no state and performs no I/O — safe to instantiate once and
    reuse. Still produces exactly `main.tf` + `versions.tf`, matching
    every single-resource renderer's output shape.
    """

    def render(
        self,
        spec: ServerlessWorkerSpec,
        *,
        module_sources: ServerlessWorkerModuleSources,
    ) -> GeneratedTerraformComposition:
        return GeneratedTerraformComposition(
            files={
                "versions.tf": render_versions_tf(),
                "main.tf": _render_main_tf(spec, module_sources),
            }
        )

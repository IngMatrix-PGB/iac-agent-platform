"""Unit tests for the deterministic DynamoDB Terraform composition
renderer (Phase 2, Batch 17). Mirrors
tests/unit/providers/aws/s3/test_s3_renderer.py's coverage for the
fields DynamoDB actually has.
"""

import ast
import inspect
import re

from iac_agent.providers.aws.dynamodb import renderer as renderer_module
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.dynamodb.renderer import (
    DEFAULT_MODULE_SOURCE,
    DynamoDBTerraformCompositionRenderer,
    GeneratedTerraformComposition,
)
from iac_agent.providers.aws.terraform_render import hcl_tags

RENDERER = DynamoDBTerraformCompositionRenderer()


def _spec(**overrides) -> DynamoDBResourceSpec:
    defaults = {
        "name": "orders-table",
        "partition_key": DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
    }
    defaults.update(overrides)
    return DynamoDBResourceSpec(**defaults)


def _render(spec: DynamoDBResourceSpec, **kwargs) -> GeneratedTerraformComposition:
    return RENDERER.render(spec, **kwargs)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_table_with_partition_key_only_renders_expected_files():
    result = _render(_spec())

    assert set(result.files) == {"versions.tf", "main.tf"}
    main_tf = result.files["main.tf"]
    assert 'module "dynamodb"' in main_tf
    assert 'name                   = "orders-table"' in main_tf
    assert 'hash_key_name          = "pk"' in main_tf
    assert 'hash_key_type          = "S"' in main_tf
    assert "range_key_name         = null" in main_tf
    assert "range_key_type         = null" in main_tf


def test_table_with_partition_and_sort_key():
    spec = _spec(sort_key=DynamoDBKeySpec(name="sk", type=DynamoDBKeyType.NUMBER))
    main_tf = _render(spec).files["main.tf"]

    assert 'range_key_name         = "sk"' in main_tf
    assert 'range_key_type         = "N"' in main_tf


def test_no_kms_key_id_attribute_is_ever_rendered():
    """Batch 17: customer-managed KMS is deliberately deferred (see
    DynamoDBEncryptionSpec's docstring) — the module block never
    contains a kms_key_id attribute at all."""
    main_tf = _render(_spec()).files["main.tf"]
    assert "kms_key_id" not in main_tf


def test_pitr_true_and_false_are_both_rendered_verbatim():
    enabled = _render(_spec(point_in_time_recovery=True)).files["main.tf"]
    disabled = _render(_spec(point_in_time_recovery=False)).files["main.tf"]

    assert "point_in_time_recovery = true" in enabled
    assert "point_in_time_recovery = false" in disabled


def test_deletion_protection_true_and_false_are_both_rendered_verbatim():
    enabled = _render(_spec(deletion_protection=True)).files["main.tf"]
    disabled = _render(_spec(deletion_protection=False)).files["main.tf"]

    assert "deletion_protection    = true" in enabled
    assert "deletion_protection    = false" in disabled


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def test_empty_tags_render_as_empty_map():
    main_tf = _render(_spec(tags={})).files["main.tf"]
    assert "tags                   = {}" in main_tf


def test_multiple_tags_render_sorted():
    spec = _spec(tags={"Service": "orders", "Team": "data"})
    main_tf = _render(spec).files["main.tf"]

    assert main_tf.index('"Service"') < main_tf.index('"Team"')


def test_tags_with_different_insertion_order_render_identically():
    spec_a = _spec(tags={"Service": "orders", "Team": "data"})
    spec_b = _spec(tags={"Team": "data", "Service": "orders"})

    assert _render(spec_a).files == _render(spec_b).files


def test_multiple_tags_with_different_key_lengths_have_aligned_equals_signs():
    """Reuses the same `hcl_tags` alignment fix proven for SQS/S3 — this
    test proves the DynamoDB renderer actually shares it, not a re-copy."""
    spec = _spec(tags={"ManagedBy": "iac-agent-platform", "Purpose": "phase2-demo"})
    main_tf = _render(spec).files["main.tf"]

    assert '    "ManagedBy" = "iac-agent-platform"\n' in main_tf
    assert '    "Purpose"   = "phase2-demo"\n' in main_tf


def test_hcl_tags_helper_is_the_shared_one():
    assert renderer_module.hcl_tags is hcl_tags


# ---------------------------------------------------------------------------
# environment field is metadata-only
# ---------------------------------------------------------------------------


def test_environment_present_does_not_change_rendered_output():
    with_env = _spec(environment="staging")
    without_env = _spec()

    assert _render(with_env).files == _render(without_env).files


def test_environment_value_never_appears_in_rendered_output():
    spec = _spec(environment="staging")
    files = _render(spec).files

    for content in files.values():
        assert "staging" not in content
        assert "environment" not in content.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_is_byte_identical_across_repeated_calls():
    spec = _spec(tags={"Service": "orders"})

    assert _render(spec).files == _render(spec).files


def test_rendering_is_byte_identical_across_separate_renderer_instances():
    spec = _spec()

    assert (
        DynamoDBTerraformCompositionRenderer().render(spec).files
        == DynamoDBTerraformCompositionRenderer().render(spec).files
    )


# ---------------------------------------------------------------------------
# Module-invocation-only invariant
# ---------------------------------------------------------------------------


def test_generated_root_contains_module_invocation():
    main_tf = _render(_spec()).files["main.tf"]
    assert 'module "dynamodb" {' in main_tf


def test_generated_root_does_not_contain_any_aws_resource_block():
    files = _render(_spec()).files

    for content in files.values():
        assert not re.search(r'resource\s+"aws_', content)


# ---------------------------------------------------------------------------
# Path / credential / capability hygiene
# ---------------------------------------------------------------------------


def test_default_module_source_contains_no_absolute_or_machine_specific_path():
    assert not DEFAULT_MODULE_SOURCE.startswith("/")
    assert "Users" not in DEFAULT_MODULE_SOURCE


def test_no_credential_values_appear_in_rendered_output():
    files = _render(_spec()).files

    for content in files.values():
        assert "AWS_ACCESS_KEY_ID" not in content
        assert "AWS_SECRET_ACCESS_KEY" not in content
        assert "access_key" not in content
        assert "secret_key" not in content


def test_renderer_module_imports_no_forbidden_dependencies():
    tree = ast.parse(inspect.getsource(renderer_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"langchain", "langgraph", "boto3", "subprocess", "requests", "httpx"}
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_renderer_module_contains_no_apply_or_destroy_capability():
    source = inspect.getsource(renderer_module)
    assert "terraform apply" not in source.lower()
    assert "terraform destroy" not in source.lower()

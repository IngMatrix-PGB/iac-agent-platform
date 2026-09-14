"""Unit tests for the deterministic S3 Terraform composition renderer
(Phase 2). Mirrors tests/unit/providers/aws/sqs/test_renderer.py's
coverage for the fields S3 actually has.
"""

import ast
import inspect
import re

from iac_agent.providers.aws.s3 import renderer as renderer_module
from iac_agent.providers.aws.s3.contract import S3EncryptionSpec, S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import (
    DEFAULT_MODULE_SOURCE,
    GeneratedTerraformComposition,
    S3TerraformCompositionRenderer,
)
from iac_agent.providers.aws.terraform_render import hcl_tags

RENDERER = S3TerraformCompositionRenderer()


def _render(spec: S3ResourceSpec, **kwargs) -> GeneratedTerraformComposition:
    return RENDERER.render(spec, **kwargs)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_bucket_with_defaults_renders_expected_files():
    result = _render(S3ResourceSpec(name="my-example-bucket"))

    assert set(result.files) == {"versions.tf", "main.tf"}
    assert 'module "bucket"' in result.files["main.tf"]
    assert 'name       = "my-example-bucket"' in result.files["main.tf"]


def test_versioning_true_and_false_are_both_rendered_verbatim():
    enabled = _render(S3ResourceSpec(name="my-example-bucket", versioning=True)).files["main.tf"]
    disabled = _render(S3ResourceSpec(name="my-example-bucket", versioning=False)).files["main.tf"]

    assert "versioning = true" in enabled
    assert "versioning = false" in disabled


def test_kms_key_reference_is_rendered_as_quoted_string():
    spec = S3ResourceSpec(
        name="my-example-bucket", encryption=S3EncryptionSpec(kms_key_id="alias/aws/s3")
    )
    main_tf = _render(spec).files["main.tf"]

    assert 'kms_key_id = "alias/aws/s3"' in main_tf


def test_aws_managed_encryption_renders_null_kms_key_id():
    main_tf = _render(S3ResourceSpec(name="my-example-bucket")).files["main.tf"]
    assert "kms_key_id = null" in main_tf


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def test_empty_tags_render_as_empty_map():
    main_tf = _render(S3ResourceSpec(name="my-example-bucket", tags={})).files["main.tf"]
    assert "tags       = {}" in main_tf


def test_multiple_tags_render_sorted():
    spec = S3ResourceSpec(name="my-example-bucket", tags={"Service": "reports", "Team": "data"})
    main_tf = _render(spec).files["main.tf"]

    assert main_tf.index('"Service"') < main_tf.index('"Team"')


def test_tags_with_different_insertion_order_render_identically():
    spec_a = S3ResourceSpec(name="my-example-bucket", tags={"Service": "reports", "Team": "data"})
    spec_b = S3ResourceSpec(name="my-example-bucket", tags={"Team": "data", "Service": "reports"})

    assert _render(spec_a).files == _render(spec_b).files


def test_multiple_tags_with_different_key_lengths_have_aligned_equals_signs():
    """Reuses the same `hcl_tags` alignment fix proven for SQS — this
    test proves the S3 renderer actually shares it, not a re-copy."""
    spec = S3ResourceSpec(
        name="my-example-bucket",
        tags={"ManagedBy": "iac-agent-platform", "Purpose": "phase2-demo"},
    )
    main_tf = _render(spec).files["main.tf"]

    assert '    "ManagedBy" = "iac-agent-platform"\n' in main_tf
    assert '    "Purpose"   = "phase2-demo"\n' in main_tf


def test_hcl_tags_helper_is_the_shared_one():
    assert renderer_module.hcl_tags is hcl_tags


# ---------------------------------------------------------------------------
# environment field is metadata-only
# ---------------------------------------------------------------------------


def test_environment_present_does_not_change_rendered_output():
    with_env = S3ResourceSpec(name="my-example-bucket", environment="staging")
    without_env = S3ResourceSpec(name="my-example-bucket")

    assert _render(with_env).files == _render(without_env).files


def test_environment_value_never_appears_in_rendered_output():
    spec = S3ResourceSpec(name="my-example-bucket", environment="staging")
    files = _render(spec).files

    for content in files.values():
        assert "staging" not in content
        assert "environment" not in content.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_is_byte_identical_across_repeated_calls():
    spec = S3ResourceSpec(name="my-example-bucket", tags={"Service": "reports"})

    assert _render(spec).files == _render(spec).files


def test_rendering_is_byte_identical_across_separate_renderer_instances():
    spec = S3ResourceSpec(name="my-example-bucket")

    assert (
        S3TerraformCompositionRenderer().render(spec).files
        == S3TerraformCompositionRenderer().render(spec).files
    )


# ---------------------------------------------------------------------------
# Module-invocation-only invariant
# ---------------------------------------------------------------------------


def test_generated_root_contains_module_invocation():
    main_tf = _render(S3ResourceSpec(name="my-example-bucket")).files["main.tf"]
    assert 'module "bucket" {' in main_tf


def test_generated_root_does_not_contain_any_aws_resource_block():
    files = _render(S3ResourceSpec(name="my-example-bucket")).files

    for content in files.values():
        assert not re.search(r'resource\s+"aws_', content)


# ---------------------------------------------------------------------------
# Path / credential / capability hygiene
# ---------------------------------------------------------------------------


def test_default_module_source_contains_no_absolute_or_machine_specific_path():
    assert not DEFAULT_MODULE_SOURCE.startswith("/")
    assert "Users" not in DEFAULT_MODULE_SOURCE


def test_no_credential_values_appear_in_rendered_output():
    files = _render(S3ResourceSpec(name="my-example-bucket")).files

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

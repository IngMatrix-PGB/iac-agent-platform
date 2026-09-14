"""Unit tests for the deterministic Lambda Terraform composition
renderer (Phase 2, Batch 18). Mirrors
tests/unit/providers/aws/dynamodb/test_dynamodb_renderer.py's coverage
for the fields Lambda actually has.
"""

import ast
import inspect
import re

from iac_agent.providers.aws.lambda_function import renderer as renderer_module
from iac_agent.providers.aws.lambda_function.contract import (
    LambdaArchitecture,
    LambdaResourceSpec,
    LambdaTracingMode,
)
from iac_agent.providers.aws.lambda_function.renderer import (
    DEFAULT_MODULE_SOURCE,
    GeneratedTerraformComposition,
    LambdaTerraformCompositionRenderer,
)
from iac_agent.providers.aws.terraform_render import hcl_tags

RENDERER = LambdaTerraformCompositionRenderer()


def _spec(**overrides) -> LambdaResourceSpec:
    defaults = {"name": "orders-processor", "handler": "app.handler"}
    defaults.update(overrides)
    return LambdaResourceSpec(**defaults)


def _render(spec: LambdaResourceSpec, **kwargs) -> GeneratedTerraformComposition:
    return RENDERER.render(spec, **kwargs)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_function_with_defaults_renders_expected_files():
    result = _render(_spec())

    assert set(result.files) == {"versions.tf", "main.tf"}
    main_tf = result.files["main.tf"]
    assert 'module "lambda"' in main_tf
    assert 'name                  = "orders-processor"' in main_tf
    assert 'handler               = "app.handler"' in main_tf
    assert 'runtime               = "python3.12"' in main_tf


def test_architecture_both_values_are_rendered_verbatim():
    x86 = _render(_spec(architecture=LambdaArchitecture.X86_64)).files["main.tf"]
    arm = _render(_spec(architecture=LambdaArchitecture.ARM64)).files["main.tf"]

    assert 'architecture          = "x86_64"' in x86
    assert 'architecture          = "arm64"' in arm


def test_memory_and_timeout_render_as_bare_numbers():
    main_tf = _render(_spec(memory_size_mb=512, timeout_seconds=60)).files["main.tf"]
    assert "memory_size_mb        = 512" in main_tf
    assert "timeout_seconds       = 60" in main_tf


def test_reserved_concurrency_set_renders_the_number():
    main_tf = _render(_spec(reserved_concurrency=5)).files["main.tf"]
    assert "reserved_concurrency  = 5" in main_tf


def test_reserved_concurrency_omitted_renders_null():
    main_tf = _render(_spec()).files["main.tf"]
    assert "reserved_concurrency  = null" in main_tf


def test_reserved_concurrency_zero_is_distinguishable_from_null():
    """0 (fully throttled) must never render as `null` (unset)."""
    zero_main_tf = _render(_spec(reserved_concurrency=0)).files["main.tf"]
    none_main_tf = _render(_spec()).files["main.tf"]

    assert "reserved_concurrency  = 0" in zero_main_tf
    assert "reserved_concurrency  = null" in none_main_tf


def test_tracing_mode_both_values_are_rendered_verbatim():
    active = _render(_spec(tracing_mode=LambdaTracingMode.ACTIVE)).files["main.tf"]
    pass_through = _render(_spec(tracing_mode=LambdaTracingMode.PASS_THROUGH)).files["main.tf"]

    assert 'tracing_mode          = "Active"' in active
    assert 'tracing_mode          = "PassThrough"' in pass_through


def test_log_retention_days_renders_as_bare_number():
    main_tf = _render(_spec(log_retention_days=90)).files["main.tf"]
    assert "log_retention_days    = 90" in main_tf


# ---------------------------------------------------------------------------
# Environment variables and tags
# ---------------------------------------------------------------------------


def test_empty_environment_variables_render_as_empty_map():
    main_tf = _render(_spec()).files["main.tf"]
    assert "environment_variables = {}" in main_tf


def test_environment_variables_render_sorted():
    spec = _spec(environment_variables={"SERVICE_NAME": "orders", "LOG_LEVEL": "INFO"})
    main_tf = _render(spec).files["main.tf"]
    assert main_tf.index('"LOG_LEVEL"') < main_tf.index('"SERVICE_NAME"')


def test_environment_variables_with_different_insertion_order_render_identically():
    spec_a = _spec(environment_variables={"AA": "1", "BB": "2"})
    spec_b = _spec(environment_variables={"BB": "2", "AA": "1"})
    assert _render(spec_a).files == _render(spec_b).files


def test_empty_tags_render_as_empty_map():
    main_tf = _render(_spec(tags={})).files["main.tf"]
    assert "tags                  = {}" in main_tf


def test_multiple_tags_render_sorted():
    spec = _spec(tags={"Service": "orders", "Team": "data"})
    main_tf = _render(spec).files["main.tf"]
    assert main_tf.index('"Service"') < main_tf.index('"Team"')


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


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_is_byte_identical_across_repeated_calls():
    spec = _spec(environment_variables={"LOG_LEVEL": "INFO"}, tags={"Service": "orders"})
    assert _render(spec).files == _render(spec).files


def test_rendering_is_byte_identical_across_separate_renderer_instances():
    spec = _spec()
    assert (
        LambdaTerraformCompositionRenderer().render(spec).files
        == LambdaTerraformCompositionRenderer().render(spec).files
    )


# ---------------------------------------------------------------------------
# Module-invocation-only invariant
# ---------------------------------------------------------------------------


def test_generated_root_contains_module_invocation():
    main_tf = _render(_spec()).files["main.tf"]
    assert 'module "lambda" {' in main_tf


def test_generated_root_does_not_contain_any_aws_resource_block():
    files = _render(_spec()).files
    for content in files.values():
        assert not re.search(r'resource\s+"aws_', content)


def test_generated_root_does_not_contain_iam_terms():
    """The IAM execution role is entirely a trusted-module implementation
    detail — no IAM policy JSON is ever generated by this renderer."""
    files = _render(_spec()).files
    for content in files.values():
        assert "aws_iam" not in content
        assert "assume_role_policy" not in content
        assert "sts:AssumeRole" not in content


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

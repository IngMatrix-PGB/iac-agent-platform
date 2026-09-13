"""Unit tests for the deterministic SQS Terraform composition renderer.

Covers: correct module invocation, no raw aws_* resource blocks, null/
optional value rendering, tag canonicalization and escaping, and the
hard determinism invariant (same spec -> byte-identical output,
independent of tag insertion order and of the `environment` field).
"""

import ast
import inspect
import re

from iac_agent.providers.aws.sqs import renderer as renderer_module
from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import (
    DEFAULT_MODULE_SOURCE,
    GeneratedTerraformComposition,
    TerraformCompositionRenderer,
    _hcl_string,
)

RENDERER = TerraformCompositionRenderer()


def _render(spec: SQSResourceSpec, **kwargs) -> GeneratedTerraformComposition:
    return RENDERER.render(spec, **kwargs)


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


def test_standard_queue_with_defaults_renders_expected_files():
    result = _render(SQSResourceSpec(name="order-events"))

    assert set(result.files) == {"versions.tf", "main.tf"}
    assert 'module "queue"' in result.files["main.tf"]
    assert 'name                       = "order-events"' in result.files["main.tf"]


def test_queue_with_dlq_enabled_renders_dlq_true_and_max_receive_count():
    spec = SQSResourceSpec(name="order-events", dlq=DlqSpec(enabled=True, max_receive_count=7))
    main_tf = _render(spec).files["main.tf"]

    assert "dlq_enabled                = true" in main_tf
    assert "max_receive_count          = 7" in main_tf


def test_queue_with_dlq_disabled_renders_null_max_receive_count():
    spec = SQSResourceSpec(name="order-events", dlq=DlqSpec(enabled=False, max_receive_count=None))
    main_tf = _render(spec).files["main.tf"]

    assert "dlq_enabled                = false" in main_tf
    assert "max_receive_count          = null" in main_tf


def test_fifo_queue_renders_fifo_true_and_fifo_name():
    spec = SQSResourceSpec(name="order-processing.fifo", fifo=True)
    main_tf = _render(spec).files["main.tf"]

    assert "fifo                       = true" in main_tf
    assert 'name                       = "order-processing.fifo"' in main_tf


def test_kms_key_reference_is_rendered_as_quoted_string():
    spec = SQSResourceSpec(
        name="order-events", encryption=EncryptionSpec(kms_key_id="alias/aws/sqs")
    )
    main_tf = _render(spec).files["main.tf"]

    assert 'kms_key_id                 = "alias/aws/sqs"' in main_tf


def test_aws_managed_encryption_renders_null_kms_key_id():
    spec = SQSResourceSpec(name="order-events")
    main_tf = _render(spec).files["main.tf"]

    assert "kms_key_id                 = null" in main_tf


def test_custom_numeric_values_are_rendered_verbatim():
    spec = SQSResourceSpec(
        name="order-events",
        visibility_timeout_seconds=120,
        message_retention_seconds=86400,
        delay_seconds=15,
    )
    main_tf = _render(spec).files["main.tf"]

    assert "visibility_timeout_seconds = 120" in main_tf
    assert "message_retention_seconds  = 86400" in main_tf
    assert "delay_seconds              = 15" in main_tf


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


def test_empty_tags_render_as_empty_map():
    spec = SQSResourceSpec(name="order-events", tags={})
    main_tf = _render(spec).files["main.tf"]

    assert "tags                       = {}" in main_tf


def test_multiple_tags_render_sorted():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders", "Team": "platform"})
    main_tf = _render(spec).files["main.tf"]

    service_pos = main_tf.index('"Service"')
    team_pos = main_tf.index('"Team"')
    assert service_pos < team_pos  # sorted alphabetically regardless of dict insertion order


def test_tags_with_different_insertion_order_render_identically():
    spec_a = SQSResourceSpec(name="order-events", tags={"Service": "orders", "Team": "platform"})
    spec_b = SQSResourceSpec(name="order-events", tags={"Team": "platform", "Service": "orders"})

    assert _render(spec_a).files == _render(spec_b).files


def test_no_organization_specific_tags_are_injected():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders"})
    main_tf = _render(spec).files["main.tf"]

    for forbidden in ("company", "owner", "cost-center", "cost_center", "organization"):
        assert forbidden not in main_tf.lower()
    # Only the caller-supplied tag key/value are present — nothing else.
    assert main_tf.count('"Service"') + main_tf.count('"orders"') >= 2


# ---------------------------------------------------------------------------
# environment field is metadata-only
# ---------------------------------------------------------------------------


def test_environment_present_does_not_change_rendered_output():
    with_env = SQSResourceSpec(name="order-events", environment="staging")
    without_env = SQSResourceSpec(name="order-events")

    assert _render(with_env).files == _render(without_env).files


def test_environment_value_never_appears_in_rendered_output():
    spec = SQSResourceSpec(name="order-events", environment="staging")
    files = _render(spec).files

    for content in files.values():
        assert "staging" not in content
        assert "environment" not in content.lower()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_rendering_is_byte_identical_across_repeated_calls():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders"})

    first = _render(spec)
    second = _render(spec)

    assert first.files == second.files


def test_rendering_is_byte_identical_across_separate_renderer_instances():
    spec = SQSResourceSpec(name="order-events")

    assert (
        TerraformCompositionRenderer().render(spec).files
        == TerraformCompositionRenderer().render(spec).files
    )


# ---------------------------------------------------------------------------
# Module-invocation-only invariant
# ---------------------------------------------------------------------------


def test_generated_root_contains_module_invocation():
    main_tf = _render(SQSResourceSpec(name="order-events")).files["main.tf"]

    assert 'module "queue" {' in main_tf


def test_generated_root_does_not_contain_aws_sqs_queue_resource_block():
    files = _render(SQSResourceSpec(name="order-events")).files

    for content in files.values():
        assert "aws_sqs_queue" not in content


def test_generated_root_does_not_contain_any_aws_resource_block():
    files = _render(SQSResourceSpec(name="order-events")).files

    for content in files.values():
        assert not re.search(r'resource\s+"aws_', content)


# ---------------------------------------------------------------------------
# Path / credential / capability hygiene
# ---------------------------------------------------------------------------


def test_default_module_source_contains_no_absolute_or_machine_specific_path():
    assert not DEFAULT_MODULE_SOURCE.startswith("/")
    assert "Users" not in DEFAULT_MODULE_SOURCE
    assert ":\\" not in DEFAULT_MODULE_SOURCE
    assert "file://" not in DEFAULT_MODULE_SOURCE


def test_no_absolute_developer_path_appears_in_rendered_output():
    files = _render(SQSResourceSpec(name="order-events")).files

    for content in files.values():
        assert "/Users/" not in content
        assert "C:\\" not in content
        assert "file://" not in content


def test_no_credential_values_appear_in_rendered_output():
    files = _render(SQSResourceSpec(name="order-events")).files

    for content in files.values():
        assert "AWS_ACCESS_KEY_ID" not in content
        assert "AWS_SECRET_ACCESS_KEY" not in content
        assert "access_key" not in content
        assert "secret_key" not in content


def test_renderer_module_imports_no_forbidden_dependencies():
    """Inspect actual import statements (via ast), not docstrings/comments
    that merely mention these names while explaining what is forbidden."""
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


# ---------------------------------------------------------------------------
# HCL escaping (direct unit tests on the escaping helper)
# ---------------------------------------------------------------------------


def test_hcl_string_escapes_quotes_and_backslashes():
    rendered = _hcl_string('va"lue\\with\\backslash')

    assert rendered == '"va\\"lue\\\\with\\\\backslash"'


def test_hcl_string_escapes_template_interpolation_marker():
    rendered = _hcl_string("${malicious}")

    assert rendered == '"$${malicious}"'


def test_hcl_string_escapes_template_directive_marker():
    rendered = _hcl_string("%{if true}danger%{endif}")

    assert "%%{if true}" in rendered
    assert "%%{endif}" in rendered


def test_hcl_string_escapes_newlines_and_control_characters():
    rendered = _hcl_string("line1\nline2\ttabbed")

    assert rendered == '"line1\\nline2\\ttabbed"'
    assert "\n" not in rendered
    assert "\t" not in rendered


def test_tag_value_with_special_characters_is_escaped_in_composition():
    spec = SQSResourceSpec(
        name="order-events",
        tags={"Note": 'quote " backslash \\ interpolation ${x} directive %{y}'},
    )
    main_tf = _render(spec).files["main.tf"]

    # Every occurrence of the raw marker must be accounted for by an
    # escaped occurrence — i.e. "${x}" never appears on its own, only
    # as a substring of the escaped "$${x}" (same reasoning for %{y}).
    assert main_tf.count("$${x}") == 1
    assert main_tf.count("${x}") == main_tf.count("$${x}")
    assert main_tf.count("%%{y}") == 1
    assert main_tf.count("%{y}") == main_tf.count("%%{y}")

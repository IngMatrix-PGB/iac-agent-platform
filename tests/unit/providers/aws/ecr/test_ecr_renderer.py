"""Unit tests for the deterministic ECR Terraform composition renderer."""

from __future__ import annotations

import re

from iac_agent.providers.aws.ecr.contract import EcrImageTagMutability, EcrResourceSpec
from iac_agent.providers.aws.ecr.renderer import (
    DEFAULT_MODULE_SOURCE,
    EcrTerraformCompositionRenderer,
)
from iac_agent.providers.aws.terraform_render import render_versions_tf

RENDERER = EcrTerraformCompositionRenderer()


def test_default_module_source():
    assert DEFAULT_MODULE_SOURCE == "../../terraform/modules/ecr"


def test_render_writes_main_and_versions_only():
    result = RENDERER.render(EcrResourceSpec(name="orders"))
    assert set(result.files) == {"main.tf", "versions.tf"}


def test_main_tf_instantiates_one_module_and_no_raw_resource():
    main_tf = RENDERER.render(EcrResourceSpec(name="orders")).files["main.tf"]
    assert len(re.findall(r'module "ecr"', main_tf)) == 1
    assert 'resource "aws_ecr_repository"' not in main_tf
    assert 'name                 = "orders"' in main_tf
    assert 'image_tag_mutability = "IMMUTABLE"' in main_tf
    assert "scan_on_push         = true" in main_tf


def test_root_module_does_not_pass_encryption_or_omitted_arguments():
    main_tf = RENDERER.render(EcrResourceSpec(name="orders")).files["main.tf"]
    assert "encryption_type" not in main_tf
    assert "kms_key" not in main_tf
    assert "force_delete" not in main_tf
    assert "lifecycle" not in main_tf


def test_versions_tf_matches_the_shared_renderer():
    result = RENDERER.render(EcrResourceSpec(name="orders"))
    assert result.files["versions.tf"] == render_versions_tf()


def test_two_renders_of_the_same_spec_are_byte_identical():
    spec = EcrResourceSpec(name="team/service", tags={"owner": "platform"})
    assert RENDERER.render(spec).files == RENDERER.render(spec).files


def test_mutable_and_scan_disabled_are_rendered_verbatim():
    spec = EcrResourceSpec(
        name="orders",
        image_tag_mutability=EcrImageTagMutability.MUTABLE,
        scan_on_push=False,
    )
    main_tf = RENDERER.render(spec).files["main.tf"]
    assert 'image_tag_mutability = "MUTABLE"' in main_tf
    assert "IMMUTABLE" not in main_tf
    assert "scan_on_push         = false" in main_tf

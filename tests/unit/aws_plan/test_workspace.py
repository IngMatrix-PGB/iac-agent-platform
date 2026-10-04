"""Trusted V3 workspace reconstruction for one canonical SQS spec."""

from __future__ import annotations

from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.providers.aws.terraform_render import AWS_REGION

_REPO = __file__


def test_workspace_uses_trusted_module_and_real_provider(tmp_path):
    from pathlib import Path

    from iac_agent.aws_plan.workspace import build_v3_workspace
    from iac_agent.providers.aws.terraform_render import render_versions_tf

    spec = SQSResourceSpec(name="order-events")
    module_dir = Path(_REPO).resolve().parents[3] / "terraform" / "modules" / "sqs"
    destination = tmp_path / "workspace"
    build_v3_workspace(spec, module_source_dir=module_dir, destination=destination)

    provider = (destination / "provider.tf").read_text(encoding="utf-8")
    main_tf = (destination / "main.tf").read_text(encoding="utf-8")
    assert f'region = "{AWS_REGION}"' in provider
    for flag in (
        "skip_credentials_validation",
        "skip_requesting_account_id",
        "skip_metadata_api_check",
        "skip_region_validation",
    ):
        assert flag not in provider
        assert flag not in main_tf
    assert (destination / "versions.tf").read_text(encoding="utf-8") == render_versions_tf()
    assert 'source = "./modules/sqs"' in main_tf
    assert 'provider "aws"' not in main_tf
    assert (destination / "modules" / "sqs" / "main.tf").read_bytes() == (
        module_dir / "main.tf"
    ).read_bytes()


def test_proposal_main_tf_is_not_the_workspace_file(tmp_path):
    from pathlib import Path

    from iac_agent.aws_plan.workspace import build_v3_workspace

    spec = SQSResourceSpec(name="order-events")
    proposal = TerraformCompositionRenderer().render(spec).files["main.tf"]
    module_dir = Path(_REPO).resolve().parents[3] / "terraform" / "modules" / "sqs"
    destination = tmp_path / "workspace"
    build_v3_workspace(spec, module_source_dir=module_dir, destination=destination)
    planned = (destination / "main.tf").read_text(encoding="utf-8")
    assert "skip_credentials_validation" in proposal
    assert planned != proposal

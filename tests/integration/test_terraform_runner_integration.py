"""Integration proof for TerraformRunner against the real pipeline.

SQSResourceSpec -> TerraformCompositionRenderer -> write_to(tmp_path) ->
TerraformRunner.fmt/init/validate/plan/show_json, using the real
Terraform binary and the trusted terraform/modules/sqs module.

This is deliberately independent of the hand-authored Batch 3 fixture
(tests/terraform/sqs/) and of Batch 4's own integration test — it
proves TerraformRunner specifically, driving the real CLI through the
runner's public API rather than ad hoc subprocess calls.

TerraformRunner's default environment construction only ever copies an
explicit PATH/HOME allowlist from the host — so simply constructing
TerraformRunner() here is already credential-free by design, regardless
of whatever AWS_* variables the developer's own shell happens to
export. Placeholder credentials are supplied only via an explicit
env_overrides on the plan() call, exactly as Batch 3/4 proved.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from iac_agent.execution.terraform_runner import CommandResult, TerraformRunner
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None,
    reason="terraform binary not available on PATH",
)


def test_terraform_runner_drives_renderer_output_to_a_credential_free_plan(tmp_path):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    # Default construction: only PATH/HOME are ever copied from the host,
    # so no ambient AWS_PROFILE/AWS_ACCESS_KEY_ID/AWS_SESSION_TOKEN the
    # developer's shell might have set can reach Terraform through this
    # runner, by construction — not by luck.
    runner = TerraformRunner()

    fmt_result = runner.fmt(tmp_path)
    assert isinstance(fmt_result, CommandResult)
    assert fmt_result.returncode == 0

    init_result = runner.init(tmp_path)
    assert init_result.returncode == 0

    validate_result = runner.validate(tmp_path)
    assert validate_result.returncode == 0
    assert "Success" in validate_result.stdout

    plan_result = runner.plan(
        tmp_path,
        env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
    )
    assert plan_result.returncode == 0
    assert "2 to add, 0 to change, 0 to destroy" in plan_result.stdout

    plan_json = runner.show_json(tmp_path)

    resource_changes = plan_json["resource_changes"]
    assert len(resource_changes) == 2

    actions_by_address = {rc["address"]: rc["change"]["actions"] for rc in resource_changes}
    assert actions_by_address == {
        "module.queue.aws_sqs_queue.this": ["create"],
        "module.queue.aws_sqs_queue.dlq[0]": ["create"],
    }
    assert all("delete" not in actions for actions in actions_by_address.values())

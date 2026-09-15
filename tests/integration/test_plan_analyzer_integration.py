"""Integration proof: the full real pipeline through the plan analyzer.

SQSResourceSpec -> TerraformCompositionRenderer -> write_to(tmp_path) ->
TerraformRunner.fmt/init/validate/plan/show_json -> analyze_plan ->
PlanSummary, using the real Terraform 1.16.1 binary and the trusted
terraform/modules/sqs module. No manually fabricated plan JSON is used
here — that is reserved for the synthetic destructive-fixture unit
tests in test_plan_analyzer.py, since exercising a real destroy/replace
plan would require pre-existing Terraform state, which Phase 1 never
manages.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from iac_agent.domain.plan import PlanAction
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def test_analyze_plan_on_real_dlq_enabled_composition(tmp_path, terraform_test_env):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    runner = TerraformRunner(base_env=terraform_test_env)
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(
        tmp_path,
        env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
    )
    plan_json = runner.show_json(tmp_path)

    summary = analyze_plan(plan_json)

    assert set(summary.resources_to_add) == {
        "module.queue.aws_sqs_queue.this",
        "module.queue.aws_sqs_queue.dlq[0]",
    }
    assert summary.resources_to_change == ()
    assert summary.resources_to_destroy == ()
    assert summary.destructive_change_detected is False
    assert len(summary.resource_changes) == 2
    assert all(rc.action is PlanAction.CREATE for rc in summary.resource_changes)
    assert all(rc.destructive is False for rc in summary.resource_changes)

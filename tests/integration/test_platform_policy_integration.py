"""Integration proof: the full real pipeline through platform policy evaluation.

SQSResourceSpec -> TerraformCompositionRenderer -> write_to(tmp_path) ->
TerraformRunner.fmt/init/validate/plan/show_json -> analyze_plan ->
evaluate_platform_policies -> PolicyEvaluation, using the real
Terraform 1.16.1 binary and the trusted terraform/modules/sqs module.

This exercises only the create-only / encrypted / DLQ-enabled PASS
path for real. WARN (DLQ disabled) and BLOCK (destructive plan) are
proven at the unit level in test_platform_policies.py with synthetic
PlanSummary values — reproducing a real destructive Terraform plan
would require pre-existing state, which Phase 1 never manages, and
Checkov is intentionally out of scope for this batch.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.platform import (
    SQS_DLQ_RECOMMENDED,
    SQS_ENCRYPTION_REQUIRED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None,
    reason="terraform binary not available on PATH",
)


def test_platform_policies_pass_for_a_real_encrypted_dlq_enabled_plan(tmp_path):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    runner = TerraformRunner()
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(
        tmp_path,
        env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
    )
    plan_json = runner.show_json(tmp_path)
    plan_summary = analyze_plan(plan_json)

    evaluation = evaluate_platform_policies(spec, plan_summary)

    assert len(evaluation.findings) == 3
    findings_by_id = {f.policy_id: f for f in evaluation.findings}

    assert findings_by_id[SQS_ENCRYPTION_REQUIRED].status is PolicyStatus.PASS
    assert findings_by_id[SQS_DLQ_RECOMMENDED].status is PolicyStatus.PASS
    assert findings_by_id[TF_NO_DESTRUCTIVE_CHANGES].status is PolicyStatus.PASS
    assert evaluation.overall_status is PolicyStatus.PASS

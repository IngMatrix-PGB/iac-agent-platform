"""Integration proof: the full real pipeline through the security gate.

SQSResourceSpec -> TerraformCompositionRenderer -> write_to(tmp_path) ->
  (TerraformRunner.fmt/init/validate/plan/show_json -> analyze_plan ->
   evaluate_platform_policies -> PolicyEvaluation)
  and
  (CheckovAdapter.scan -> CheckovScanResult)
-> evaluate_security_gate -> SecurityGateResult

Using the real Terraform binary, the real trusted SQS module, and the
real Checkov binary. This does not hardcode Checkov's currently-clean
result into the gate itself (the gate has no idea what a "normal" scan
looks like) — it only asserts what this specific real run produced.
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
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


def test_security_gate_over_the_real_end_to_end_pipeline(tmp_path, terraform_test_env):
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
    plan_summary = analyze_plan(plan_json)

    platform_evaluation = evaluate_platform_policies(spec, plan_summary)
    checkov_result = CheckovAdapter().scan(tmp_path)

    gate_result = evaluate_security_gate(platform_evaluation, checkov_result)

    platform_ids = {f.policy_id for f in platform_evaluation.findings}
    assert platform_ids == {SQS_ENCRYPTION_REQUIRED, SQS_DLQ_RECOMMENDED, TF_NO_DESTRUCTIVE_CHANGES}
    assert platform_evaluation.overall_status is PolicyStatus.PASS

    # The gate must contain exactly the platform findings plus whatever
    # Checkov actually reported — this is a structural property, not a
    # hardcoded expectation of what Checkov "should" find.
    assert gate_result.finding_count == len(platform_evaluation.findings) + len(
        checkov_result.findings
    )
    assert gate_result.block_count == checkov_result.failed_checks

    # Based on real Batch 8 evidence the trusted module currently
    # produces a clean Checkov scan (0 failed checks) — if a future
    # Checkov version ever flags something here, this assertion (not
    # the gate itself) is what should change, per Batch 9 instructions
    # not to hardcode scanner behavior into production gate logic.
    if checkov_result.failed_checks == 0:
        assert gate_result.overall_status is PolicyStatus.PASS

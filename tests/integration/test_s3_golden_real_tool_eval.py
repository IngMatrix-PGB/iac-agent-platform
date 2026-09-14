"""OPTIONAL real-tool eval: the 'basic_secure_bucket' golden scenario run
through the real Terraform and Checkov binaries.

Mirrors tests/integration/test_sqs_golden_real_tool_eval.py: this is
the ONE S3 golden scenario exercised against real external tools — it
proves the golden dataset's "basic_secure_bucket" input genuinely
behaves as its `expected` block claims when the real pipeline runs,
not just against the typed fixtures the fast deterministic suite uses.
The other scenarios are deliberately NOT run this way.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from evals.scenarios.s3_loader import load_s3_golden_dataset
from evals.scenarios.s3_runner import DEFAULT_DATASET_PATH
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import S3TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "s3"

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)


def test_basic_secure_bucket_scenario_against_real_tools(tmp_path):
    scenarios = load_s3_golden_dataset(DEFAULT_DATASET_PATH)
    scenario = next(s for s in scenarios if s.id == "basic_secure_bucket")

    spec = S3ResourceSpec(**scenario.input)
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = S3TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    runner = TerraformRunner()
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(
        tmp_path,
        env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
    )
    plan_summary = analyze_plan(runner.show_json(tmp_path))

    platform_evaluation = evaluate_platform_policies(spec, plan_summary)
    checkov_result = CheckovAdapter().scan(tmp_path)
    gate_result = evaluate_security_gate(
        platform_evaluation, checkov_result, resource_type=ResourceType.S3
    )

    expected_status = PolicyStatus(scenario.expected.overall_security_status)
    assert gate_result.overall_status is expected_status

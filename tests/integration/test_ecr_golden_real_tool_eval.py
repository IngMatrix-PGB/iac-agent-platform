"""Real Terraform and Checkov for one ECR golden scenario.

This is not the deterministic Gate A suite. Only `basic_secure_repository`
is sent through real tools. Invalid-name scenarios stay in the offline
loader and are not planned here.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from evals.scenarios.ecr_loader import load_ecr_golden_dataset
from evals.scenarios.ecr_runner import DEFAULT_DATASET_PATH
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.ecr.renderer import EcrTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.checkov_profiles import checkov_profile_for
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "ecr"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


def test_basic_secure_repository_scenario_against_real_tools(tmp_path, terraform_test_env):
    scenarios = load_ecr_golden_dataset(DEFAULT_DATASET_PATH)
    scenario = next(item for item in scenarios if item.id == "basic_secure_repository")
    assert scenario.expected.valid is True

    spec = EcrResourceSpec(**scenario.input)
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = EcrTerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    runner = TerraformRunner(base_env=terraform_test_env)
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(
        tmp_path,
        env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
    )
    plan_summary = analyze_plan(runner.show_json(tmp_path))

    assert plan_summary.add_count == 1
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert [change.address for change in plan_summary.resource_changes] == [
        "module.ecr.aws_ecr_repository.this"
    ]

    platform_evaluation = evaluate_platform_policies(spec, plan_summary)
    checkov_result = CheckovAdapter().scan(tmp_path, profile=checkov_profile_for(ResourceType.ECR))
    gate_result = evaluate_security_gate(
        platform_evaluation, checkov_result, resource_type=ResourceType.ECR
    )

    expected_status = PolicyStatus(scenario.expected.overall_security_status)
    assert gate_result.overall_status is expected_status

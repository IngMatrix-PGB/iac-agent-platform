"""OPTIONAL real-tool eval: the 'secure_basic_table' golden scenario run
through the real Terraform and Checkov binaries (Batch 17).

Mirrors tests/integration/test_s3_golden_real_tool_eval.py: this is the
ONE DynamoDB golden scenario exercised against real external tools —
it proves the golden dataset's "secure_basic_table" input genuinely
behaves as its `expected` block claims when the real pipeline runs,
not just against the typed fixtures the fast deterministic suite uses.
The other scenarios are deliberately NOT run this way.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from evals.scenarios.dynamodb_loader import load_dynamodb_golden_dataset
from evals.scenarios.dynamodb_runner import DEFAULT_DATASET_PATH
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.dynamodb.renderer import DynamoDBTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.checkov_profiles import checkov_profile_for
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "dynamodb"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


def test_secure_basic_table_scenario_against_real_tools(tmp_path, terraform_test_env):
    scenarios = load_dynamodb_golden_dataset(DEFAULT_DATASET_PATH)
    scenario = next(s for s in scenarios if s.id == "secure_basic_table")

    spec = DynamoDBResourceSpec(**scenario.input)
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = DynamoDBTerraformCompositionRenderer().render(spec, module_source=module_source)
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

    platform_evaluation = evaluate_platform_policies(spec, plan_summary)
    checkov_result = CheckovAdapter().scan(
        tmp_path, profile=checkov_profile_for(ResourceType.DYNAMODB)
    )
    gate_result = evaluate_security_gate(
        platform_evaluation, checkov_result, resource_type=ResourceType.DYNAMODB
    )

    expected_status = PolicyStatus(scenario.expected.overall_security_status)
    assert gate_result.overall_status is expected_status

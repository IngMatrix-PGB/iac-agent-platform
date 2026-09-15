"""OPTIONAL real-tool eval: the 'secure_basic_function' golden scenario
run through the real Terraform and Checkov binaries (Batch 18).

Mirrors tests/integration/test_dynamodb_golden_real_tool_eval.py: this
is the ONE Lambda golden scenario exercised against real external
tools — it proves the golden dataset's "secure_basic_function" input
genuinely behaves as its `expected` block claims when the real pipeline
runs (including the real trusted `terraform/modules/lambda` module and
the real Checkov binary with Lambda's approved five-check skip
profile), not just against the typed fixtures the fast deterministic
suite uses. The other scenarios are deliberately NOT run this way.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from evals.scenarios.lambda_loader import load_lambda_golden_dataset
from evals.scenarios.lambda_runner import DEFAULT_DATASET_PATH
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.lambda_function.renderer import LambdaTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.checkov_profiles import checkov_profile_for
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "lambda"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


def test_secure_basic_function_scenario_against_real_tools(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    scenarios = load_lambda_golden_dataset(DEFAULT_DATASET_PATH)
    scenario = next(s for s in scenarios if s.id == "secure_basic_function")

    spec = LambdaResourceSpec(**scenario.input)
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = LambdaTerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    runner = TerraformRunner(base_env=terraform_test_env)
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(tmp_path, env_overrides=terraform_plan_env_overrides)
    plan_summary = analyze_plan(runner.show_json(tmp_path))

    platform_evaluation = evaluate_platform_policies(spec, plan_summary)
    checkov_result = CheckovAdapter().scan(
        tmp_path, profile=checkov_profile_for(ResourceType.LAMBDA)
    )
    gate_result = evaluate_security_gate(
        platform_evaluation, checkov_result, resource_type=ResourceType.LAMBDA
    )

    expected_status = PolicyStatus(scenario.expected.overall_security_status)
    assert gate_result.overall_status is expected_status

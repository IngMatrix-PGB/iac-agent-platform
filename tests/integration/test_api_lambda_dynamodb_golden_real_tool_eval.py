"""OPTIONAL real-tool eval: the 'secure_defaults' golden scenario run
through the real Terraform and Checkov binaries (Batch 26, Gate B,
Task 17).

Mirrors tests/integration/test_api_lambda_golden_real_tool_eval.py:
this is the ONE api_lambda_dynamodb golden scenario exercised against
real external tools — it proves the golden dataset's "secure_defaults"
input genuinely behaves as its `expected` block claims when the real
pipeline runs (all three real trusted modules, the composition-owned
relationship resources, and the real Checkov binary with the
composition's now-frozen, empirically-derived skip profile), not just
against the typed fixtures the fast deterministic suite (Gate A, Task
13) uses. The other scenarios are deliberately NOT run this way — this
result must never be conflated with the deterministic 11/11 Gate-A
result.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from evals.scenarios.api_lambda_dynamodb_loader import load_api_lambda_dynamodb_golden_dataset
from evals.scenarios.api_lambda_dynamodb_runner import DEFAULT_DATASET_PATH
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.api_lambda_dynamodb.renderer import (
    ApiLambdaDynamoDbModuleSources,
    ApiLambdaDynamoDbTerraformRenderer,
)
from iac_agent.compositions.resource import composition_type_of
from iac_agent.domain.security import PolicyStatus
from iac_agent.execution.plan_analyzer import analyze_plan
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.policies.composition import (
    REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE,
    evaluate_composition_policies,
)
from iac_agent.security.checkov import CheckovAdapter
from iac_agent.security.composition_checkov_profiles import composition_checkov_profile_for
from iac_agent.security.gate import evaluate_security_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_MODULES_ROOT = _REPO_ROOT / "terraform" / "modules"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


def test_secure_defaults_scenario_against_real_tools(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    scenarios = load_api_lambda_dynamodb_golden_dataset(DEFAULT_DATASET_PATH)
    scenario = next(s for s in scenarios if s.id == "secure_defaults")

    spec = ApiLambdaDynamoDbSpec(**scenario.input)
    module_sources = ApiLambdaDynamoDbModuleSources(
        api=os.path.relpath(_TERRAFORM_MODULES_ROOT / "api_gateway", start=tmp_path),
        function=os.path.relpath(_TERRAFORM_MODULES_ROOT / "lambda", start=tmp_path),
        table=os.path.relpath(_TERRAFORM_MODULES_ROOT / "dynamodb", start=tmp_path),
    )

    composition = ApiLambdaDynamoDbTerraformRenderer().render(spec, module_sources=module_sources)
    composition.write_to(tmp_path)

    runner = TerraformRunner(base_env=terraform_test_env)
    runner.fmt(tmp_path)
    runner.init(tmp_path)
    runner.validate(tmp_path)
    runner.plan(tmp_path, env_overrides=terraform_plan_env_overrides)
    plan_summary = analyze_plan(runner.show_json(tmp_path))

    platform_evaluation = evaluate_composition_policies(spec, plan_summary)
    composition_type = composition_type_of(spec)
    checkov_result = CheckovAdapter().scan(
        tmp_path, profile=composition_checkov_profile_for(composition_type)
    )
    gate_result = evaluate_security_gate(
        platform_evaluation,
        checkov_result,
        required_policy_ids=REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[composition_type],
    )

    expected_status = PolicyStatus(scenario.expected.overall_security_status)
    assert gate_result.overall_status is expected_status

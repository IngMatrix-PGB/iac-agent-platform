"""V3 plan environment stays separate from the V1 placeholder credentials."""

from __future__ import annotations

import pytest

from iac_agent.aws_plan.execution import ConfigurationError, v3_plan_env, v3_runner
from iac_agent.aws_plan.target import AWS_REGION
from iac_agent.execution.terraform_runner import TerraformRunner, TerraformTimeouts
from iac_agent.graph.workflow import _PLAN_ENV_OVERRIDES


def test_v3_runner_plan_timeout_is_300():
    assert v3_runner()._timeouts.plan == 300.0
    assert TerraformTimeouts().plan == 180.0


def test_v3_env_requires_session_credentials():
    env = v3_plan_env(
        {
            "AWS_ACCESS_KEY_ID": "ASIAEXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_SESSION_TOKEN": "session",
        }
    )
    assert env == {
        "AWS_ACCESS_KEY_ID": "ASIAEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "secret",
        "AWS_SESSION_TOKEN": "session",
        "AWS_DEFAULT_REGION": AWS_REGION,
    }


def test_v3_env_rejects_placeholder_keys():
    with pytest.raises(ConfigurationError):
        v3_plan_env(
            {
                "AWS_ACCESS_KEY_ID": "test",
                "AWS_SECRET_ACCESS_KEY": "test",
                "AWS_SESSION_TOKEN": "session",
            }
        )


def test_runner_has_no_apply_or_destroy():
    assert not hasattr(TerraformRunner, "apply")
    assert not hasattr(TerraformRunner, "destroy")


def test_v1_plan_overrides_unchanged():
    assert _PLAN_ENV_OVERRIDES == {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
    }

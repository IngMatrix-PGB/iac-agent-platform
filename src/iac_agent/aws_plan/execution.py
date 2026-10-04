"""V3 Terraform plan context. The V1 credential-free path stays untouched."""

from __future__ import annotations

from collections.abc import Mapping

from iac_agent.aws_plan.target import AWS_REGION, V3_PLAN_TIMEOUT_SECONDS
from iac_agent.execution.terraform_runner import TerraformRunner, TerraformTimeouts

_CREDENTIAL_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


class ConfigurationError(Exception):
    """V3 was asked to plan without a real short-lived session."""


def v3_runner() -> TerraformRunner:
    return TerraformRunner(timeouts=TerraformTimeouts(plan=V3_PLAN_TIMEOUT_SECONDS))


def v3_plan_env(source: Mapping[str, str]) -> dict[str, str]:
    missing = [key for key in _CREDENTIAL_KEYS if not source.get(key)]
    if missing:
        raise ConfigurationError("short-lived AWS session credentials are missing")
    if source["AWS_ACCESS_KEY_ID"] == "test" or source["AWS_SECRET_ACCESS_KEY"] == "test":
        raise ConfigurationError("placeholder credentials are not valid for V3")
    if source.get("AWS_DEFAULT_REGION", AWS_REGION) != AWS_REGION:
        raise ConfigurationError("V3 region is not us-east-1")
    return {
        "AWS_ACCESS_KEY_ID": source["AWS_ACCESS_KEY_ID"],
        "AWS_SECRET_ACCESS_KEY": source["AWS_SECRET_ACCESS_KEY"],
        "AWS_SESSION_TOKEN": source["AWS_SESSION_TOKEN"],
        "AWS_DEFAULT_REGION": AWS_REGION,
    }

"""Explicit presence of the two optional operator-runtime capabilities.

Classifiers read a mapping the caller supplies. They do not read the process
environment, open a client, or persist the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from iac_agent.app.config import IntentInterpreterProvider, MissingConfigurationError

INTENT_ABSENT_MESSAGE = (
    "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, "
    "IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY."
)
SOURCE_CONTROL_ABSENT_MESSAGE = (
    "Source-control publishing is not configured. Set GITHUB_OWNER, "
    "GITHUB_REPOSITORY, GITHUB_COMMIT_AUTHOR_NAME, GITHUB_COMMIT_AUTHOR_EMAIL, "
    "and GITHUB_TOKEN."
)

_GITHUB_GROUP = (
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_COMMIT_AUTHOR_NAME",
    "GITHUB_COMMIT_AUTHOR_EMAIL",
    "GITHUB_TOKEN",
)
_INTENT_GROUP = (
    "IAC_AGENT_LLM_PROVIDER",
    "IAC_AGENT_LLM_MODEL",
    "OPENAI_API_KEY",
)
_GITHUB_BASE_BRANCH = "GITHUB_BASE_BRANCH"


class CapabilityPresence(StrEnum):
    CONFIGURED = "configured"
    ABSENT = "absent"


@dataclass(frozen=True)
class RuntimeCapabilities:
    intent_interpretation: CapabilityPresence
    source_control_publishing: CapabilityPresence


def _omitted(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name)
    return value is None or value.strip() == ""


def classify_source_control_publishing(env: Mapping[str, str]) -> CapabilityPresence:
    omitted = [name for name in _GITHUB_GROUP if _omitted(env, name)]
    branch_raw = env.get(_GITHUB_BASE_BRANCH)
    branch_supplied = branch_raw is not None and branch_raw.strip() != ""
    if not omitted:
        if branch_raw is not None and branch_raw.strip() == "":
            raise MissingConfigurationError(
                "GITHUB_BASE_BRANCH must be set explicitly — "
                "GitHub publication configuration is partial"
            )
        return CapabilityPresence.CONFIGURED
    if len(omitted) == len(_GITHUB_GROUP) and (
        not branch_supplied or branch_raw.strip() == "main"
    ):
        return CapabilityPresence.ABSENT
    names = list(omitted)
    if branch_supplied and branch_raw.strip() != "main":
        names.append(_GITHUB_BASE_BRANCH)
    raise MissingConfigurationError(
        "GitHub publication configuration is partial — omitted: " + ", ".join(names)
    )


def classify_intent_interpretation(env: Mapping[str, str]) -> CapabilityPresence:
    omitted = [name for name in _INTENT_GROUP if _omitted(env, name)]
    if len(omitted) == len(_INTENT_GROUP):
        return CapabilityPresence.ABSENT
    if omitted:
        raise MissingConfigurationError(
            "Intent interpretation configuration is partial — omitted: " + ", ".join(omitted)
        )
    provider = env["IAC_AGENT_LLM_PROVIDER"].strip()
    try:
        IntentInterpreterProvider(provider)
    except ValueError as exc:
        raise MissingConfigurationError(
            "IAC_AGENT_LLM_PROVIDER has an unsupported value "
            f"{provider!r} — supported providers: "
            f"{[item.value for item in IntentInterpreterProvider]}"
        ) from exc
    return CapabilityPresence.CONFIGURED


def classify_runtime_capabilities(env: Mapping[str, str]) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        intent_interpretation=classify_intent_interpretation(env),
        source_control_publishing=classify_source_control_publishing(env),
    )

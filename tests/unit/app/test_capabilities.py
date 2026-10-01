import dataclasses

import pytest

from iac_agent.app.capabilities import (
    INTENT_ABSENT_MESSAGE,
    SOURCE_CONTROL_ABSENT_MESSAGE,
    CapabilityPresence,
    RuntimeCapabilities,
    classify_intent_interpretation,
    classify_runtime_capabilities,
    classify_source_control_publishing,
)
from iac_agent.app.config import MissingConfigurationError

_GITHUB = {
    "GITHUB_OWNER": "example-user",
    "GITHUB_REPOSITORY": "iac-agent-platform",
    "GITHUB_COMMIT_AUTHOR_NAME": "Example Bot",
    "GITHUB_COMMIT_AUTHOR_EMAIL": "example-bot@example.invalid",
    "GITHUB_TOKEN": "test-github-token-not-used",
}
_INTENT = {
    "IAC_AGENT_LLM_PROVIDER": "openai",
    "IAC_AGENT_LLM_MODEL": "gpt-test",
    "OPENAI_API_KEY": "test-openai-key-not-used",
}


def test_runtime_capabilities_exposes_only_the_two_approved_fields():
    assert [field.name for field in dataclasses.fields(RuntimeCapabilities)] == [
        "intent_interpretation",
        "source_control_publishing",
    ]
    assert {member.value for member in CapabilityPresence} == {"configured", "absent"}


def test_empty_groups_are_absent_including_default_base_branch():
    env = {"GITHUB_BASE_BRANCH": "main"}
    assert classify_source_control_publishing(env) is CapabilityPresence.ABSENT
    assert classify_intent_interpretation({}) is CapabilityPresence.ABSENT
    caps = classify_runtime_capabilities(env)
    assert caps.source_control_publishing is CapabilityPresence.ABSENT
    assert caps.intent_interpretation is CapabilityPresence.ABSENT


def test_empty_string_groups_are_absent():
    env = {name: "" for name in (*_GITHUB, *_INTENT, "GITHUB_BASE_BRANCH")}
    caps = classify_runtime_capabilities(env)
    assert caps.source_control_publishing is CapabilityPresence.ABSENT
    assert caps.intent_interpretation is CapabilityPresence.ABSENT


def test_whitespace_only_groups_are_absent():
    env = {name: "   " for name in (*_GITHUB, *_INTENT, "GITHUB_BASE_BRANCH")}
    assert classify_runtime_capabilities(env).source_control_publishing is CapabilityPresence.ABSENT
    assert classify_runtime_capabilities(env).intent_interpretation is CapabilityPresence.ABSENT


def test_complete_groups_are_configured_and_messages_name_variables_only():
    env = {**_GITHUB, **_INTENT}
    caps = classify_runtime_capabilities(env)
    assert caps.source_control_publishing is CapabilityPresence.CONFIGURED
    assert caps.intent_interpretation is CapabilityPresence.CONFIGURED
    assert "GITHUB_TOKEN" in SOURCE_CONTROL_ABSENT_MESSAGE
    assert "test-github-token-not-used" not in SOURCE_CONTROL_ABSENT_MESSAGE
    assert "OPENAI_API_KEY" in INTENT_ABSENT_MESSAGE
    assert "test-openai-key-not-used" not in INTENT_ABSENT_MESSAGE


def test_partial_github_names_omitted_variables_and_hides_the_token():
    env = {"GITHUB_OWNER": "example-user", "GITHUB_TOKEN": "test-github-token-not-used"}
    with pytest.raises(MissingConfigurationError) as exc:
        classify_source_control_publishing(env)
    text = str(exc.value)
    assert "GITHUB_REPOSITORY" in text
    assert "test-github-token-not-used" not in text


def test_non_default_branch_without_the_github_group_is_partial():
    with pytest.raises(MissingConfigurationError) as exc:
        classify_source_control_publishing({"GITHUB_BASE_BRANCH": "develop"})
    assert "GITHUB_BASE_BRANCH" in str(exc.value)
    assert "GITHUB_TOKEN" in str(exc.value)


def test_blank_branch_with_a_complete_github_group_is_partial():
    env = {**_GITHUB, "GITHUB_BASE_BRANCH": "   "}
    with pytest.raises(MissingConfigurationError) as exc:
        classify_source_control_publishing(env)
    text = str(exc.value)
    assert "GITHUB_BASE_BRANCH" in text
    assert "test-github-token-not-used" not in text


def test_partial_interpreter_names_the_omitted_variable_and_hides_the_key():
    env = {"IAC_AGENT_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "   "}
    with pytest.raises(MissingConfigurationError) as exc:
        classify_intent_interpretation(env)
    text = str(exc.value)
    assert "IAC_AGENT_LLM_MODEL" in text
    assert "OPENAI_API_KEY" in text
    assert "sk-" not in text


def test_unsupported_provider_is_invalid_when_the_group_is_otherwise_complete():
    env = {**_INTENT, "IAC_AGENT_LLM_PROVIDER": "some-other-provider"}
    with pytest.raises(MissingConfigurationError) as exc:
        classify_intent_interpretation(env)
    text = str(exc.value)
    assert "some-other-provider" in text
    assert "test-openai-key-not-used" not in text

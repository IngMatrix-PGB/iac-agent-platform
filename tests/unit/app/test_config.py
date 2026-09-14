"""Unit tests for application configuration/environment loading
(Batch 15). No filesystem I/O, no real environment mutation — every
test injects a plain dict as `env`."""

from __future__ import annotations

from pathlib import Path

import pytest

from iac_agent.app.config import (
    DEFAULT_GITHUB_BASE_BRANCH,
    DEFAULT_STATE_DB_FILENAME,
    ApplicationConfig,
    MissingConfigurationError,
    load_application_config_from_env,
    load_github_token_from_env,
)

_FULL_ENV = {
    "IAC_AGENT_WORKSPACE_ROOT": "/tmp/example-workspace",
    "IAC_AGENT_STATE_DB": "/tmp/example-workspace/state.db",
    "GITHUB_OWNER": "example-user",
    "GITHUB_REPOSITORY": "iac-agent-platform",
    "GITHUB_BASE_BRANCH": "main",
    "GITHUB_TOKEN": "fake-token-not-real",  # noqa: S105 - deliberately fake
}


def test_config_loader_reads_all_supported_variables():
    config = load_application_config_from_env(_FULL_ENV)

    assert config.workspace_root == Path("/tmp/example-workspace")
    assert config.state_db_path == Path("/tmp/example-workspace/state.db")
    assert config.github_owner == "example-user"
    assert config.github_repository == "iac-agent-platform"
    assert config.github_base_branch == "main"


def test_config_loader_defaults_state_db_under_workspace_root():
    env = dict(_FULL_ENV)
    del env["IAC_AGENT_STATE_DB"]
    config = load_application_config_from_env(env)

    assert config.state_db_path == Path("/tmp/example-workspace") / DEFAULT_STATE_DB_FILENAME


def test_config_loader_defaults_github_base_branch():
    env = dict(_FULL_ENV)
    del env["GITHUB_BASE_BRANCH"]
    config = load_application_config_from_env(env)

    assert config.github_base_branch == DEFAULT_GITHUB_BASE_BRANCH


def test_config_loader_uses_state_db_canonical_filename_by_default():
    env = {k: v for k, v in _FULL_ENV.items() if k not in ("IAC_AGENT_STATE_DB",)}
    config = load_application_config_from_env(env)

    assert config.state_db_path.name == "state.db"
    assert DEFAULT_STATE_DB_FILENAME == "state.db"


def test_missing_github_owner_is_rejected():
    env = dict(_FULL_ENV)
    del env["GITHUB_OWNER"]
    with pytest.raises(MissingConfigurationError):
        load_application_config_from_env(env)


def test_missing_github_repository_is_rejected():
    env = dict(_FULL_ENV)
    del env["GITHUB_REPOSITORY"]
    with pytest.raises(MissingConfigurationError):
        load_application_config_from_env(env)


def test_empty_github_owner_is_rejected():
    env = dict(_FULL_ENV)
    env["GITHUB_OWNER"] = ""
    with pytest.raises(MissingConfigurationError):
        load_application_config_from_env(env)


def test_missing_github_token_is_rejected():
    env = dict(_FULL_ENV)
    del env["GITHUB_TOKEN"]
    with pytest.raises(MissingConfigurationError):
        load_github_token_from_env(env)


def test_empty_github_token_is_rejected():
    with pytest.raises(MissingConfigurationError):
        load_github_token_from_env({"GITHUB_TOKEN": ""})


def test_github_token_is_never_in_repr_or_str():
    token = load_github_token_from_env(_FULL_ENV)
    assert "fake-token-not-real" not in repr(token)
    assert "fake-token-not-real" not in str(token)


def test_github_token_value_still_retrievable_explicitly():
    token = load_github_token_from_env(_FULL_ENV)
    assert token.get_secret_value() == "fake-token-not-real"


def test_application_config_has_no_token_field():
    field_names = {f for f in ApplicationConfig.__dataclass_fields__}
    assert "github_token" not in field_names
    assert "token" not in field_names

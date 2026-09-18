"""Application configuration and environment loading (Batch 15).

`ApplicationConfig` holds only non-secret settings — no GitHub token
ever appears in it, so it is always safe to log, repr, or store. The
GitHub token is loaded and passed separately, wrapped in Pydantic's
`SecretStr` (already a transitive dependency via `pydantic`, so no new
dependency was added solely for secret wrapping) so it never appears in
a repr/str by accident.

No domain module or LangGraph node reads `os.environ` — this is the
only place in the entire codebase that does.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import SecretStr

#: Canonical default filename for the SQLite checkpoint database,
#: adopted in Batch 15 in place of the earlier, unnecessarily verbose
#: example/test database filename. The persistence layer itself
#: (`iac_agent.persistence.checkpoints.open_sqlite_checkpointer`) never
#: hardcodes this — callers always supply an explicit path; this is
#: only the naming convention this application layer defaults to.
DEFAULT_STATE_DB_FILENAME = "state.db"

#: Local workspace root default — a runtime-generated, gitignored
#: directory (see .gitignore), never committed.
DEFAULT_WORKSPACE_ROOT = Path("artifacts")

#: Safe default: publishing against `main` is a reasonable default for
#: local/example use. GitHub owner/repository/token have no such
#: default — see `load_application_config_from_env`.
DEFAULT_GITHUB_BASE_BRANCH = "main"

_ENV_WORKSPACE_ROOT = "IAC_AGENT_WORKSPACE_ROOT"
_ENV_STATE_DB = "IAC_AGENT_STATE_DB"
_ENV_GITHUB_OWNER = "GITHUB_OWNER"
_ENV_GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
_ENV_GITHUB_BASE_BRANCH = "GITHUB_BASE_BRANCH"
_ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
_ENV_GITHUB_COMMIT_AUTHOR_NAME = "GITHUB_COMMIT_AUTHOR_NAME"
_ENV_GITHUB_COMMIT_AUTHOR_EMAIL = "GITHUB_COMMIT_AUTHOR_EMAIL"

#: Batch 23 — provider-neutral LLM interpreter configuration. Deliberately
#: separate from ApplicationConfig: these two config concerns (the
#: Terraform/GitHub pipeline vs. the optional natural-language intent
#: boundary) evolve independently, and a repository that never uses the
#: LLM adapter at all should never need to think about these variables.
_ENV_LLM_PROVIDER = "IAC_AGENT_LLM_PROVIDER"
_ENV_LLM_MODEL = "IAC_AGENT_LLM_MODEL"

#: OpenAI's own SDK-recognized env var name — reused as-is, mirroring
#: the precedent of reusing GITHUB_TOKEN's own conventional name rather
#: than inventing an IAC_AGENT_-prefixed wrapper for a third party's
#: credential.
_ENV_OPENAI_API_KEY = "OPENAI_API_KEY"


class MissingConfigurationError(ValueError):
    """A required configuration value has no safe default and was not
    supplied — GitHub owner/repository/commit-author identity, or (for
    GitHub-enabled runtime) the token. This project never silently
    defaults to a real user, repository, or commit identity."""


@dataclass(frozen=True)
class ApplicationConfig:
    """Non-secret application configuration — always safe to log or repr.

    The GitHub token is never a field here; it is loaded and passed
    separately (see `load_github_token_from_env` and
    `iac_agent.app.composition.open_application`) so that no code path
    can accidentally serialize or print it via this object.

    `github_commit_author_name`/`github_commit_author_email` ARE public
    metadata (any commit's author is always visible in the published
    history) and safe to hold here — unlike the token, there is no
    reason to keep them out of a repr. They still have no default:
    this project never silently attributes a generated commit to any
    specific person.

    Batch 20 removed the earlier `terraform_module_path` field: it was
    demonstrably dead configuration, not merely undocumented — it was
    never read from the environment (`load_application_config_from_env`
    always computed it from a fixed internal constant, identical to
    what `iac_agent.graph.workflow.build_sqs_workflow`'s own
    `trusted_module_dir` default parameter already resolves to), so
    passing it through to `build_sqs_workflow` in
    `iac_agent.app.composition.open_application` changed nothing at
    runtime. Trusted-module-directory resolution is fully resource/
    composition-aware in `iac_agent.graph.workflow`'s own
    `_DEFAULT_TRUSTED_MODULE_DIRS` (Batches 16-20); this config layer
    has no reason to carry a second, narrower, SQS-only copy of that
    resolution at all.
    """

    workspace_root: Path
    state_db_path: Path
    github_owner: str
    github_repository: str
    github_commit_author_name: str
    github_commit_author_email: str
    github_base_branch: str = DEFAULT_GITHUB_BASE_BRANCH


def load_application_config_from_env(env: Mapping[str, str] | None = None) -> ApplicationConfig:
    """Build `ApplicationConfig` from environment variables.

    Supported variables:
        IAC_AGENT_WORKSPACE_ROOT      (default: "artifacts")
        IAC_AGENT_STATE_DB            (default: "<workspace_root>/state.db")
        GITHUB_OWNER                  (required, no default)
        GITHUB_REPOSITORY             (required, no default)
        GITHUB_COMMIT_AUTHOR_NAME     (required, no default)
        GITHUB_COMMIT_AUTHOR_EMAIL    (required, no default)
        GITHUB_BASE_BRANCH            (default: "main")

    `env` defaults to `os.environ`; tests inject a plain dict instead of
    mutating the real process environment.
    """
    env = env if env is not None else os.environ

    workspace_root = Path(env.get(_ENV_WORKSPACE_ROOT, str(DEFAULT_WORKSPACE_ROOT)))

    state_db_env = env.get(_ENV_STATE_DB)
    state_db_path = (
        Path(state_db_env) if state_db_env else workspace_root / DEFAULT_STATE_DB_FILENAME
    )

    github_owner = env.get(_ENV_GITHUB_OWNER)
    if not github_owner:
        raise MissingConfigurationError(
            f"{_ENV_GITHUB_OWNER} must be set explicitly — there is no default GitHub owner"
        )

    github_repository = env.get(_ENV_GITHUB_REPOSITORY)
    if not github_repository:
        raise MissingConfigurationError(
            f"{_ENV_GITHUB_REPOSITORY} must be set explicitly — there is no default "
            "GitHub repository"
        )

    commit_author_name = env.get(_ENV_GITHUB_COMMIT_AUTHOR_NAME)
    if not commit_author_name:
        raise MissingConfigurationError(
            f"{_ENV_GITHUB_COMMIT_AUTHOR_NAME} must be set explicitly — there is no default "
            "commit author name"
        )

    commit_author_email = env.get(_ENV_GITHUB_COMMIT_AUTHOR_EMAIL)
    if not commit_author_email:
        raise MissingConfigurationError(
            f"{_ENV_GITHUB_COMMIT_AUTHOR_EMAIL} must be set explicitly — there is no default "
            "commit author email"
        )

    github_base_branch = env.get(_ENV_GITHUB_BASE_BRANCH, DEFAULT_GITHUB_BASE_BRANCH)

    return ApplicationConfig(
        workspace_root=workspace_root,
        state_db_path=state_db_path,
        github_owner=github_owner,
        github_repository=github_repository,
        github_commit_author_name=commit_author_name,
        github_commit_author_email=commit_author_email,
        github_base_branch=github_base_branch,
    )


def load_github_token_from_env(env: Mapping[str, str] | None = None) -> SecretStr:
    """Load the GitHub token from `GITHUB_TOKEN`, wrapped in `SecretStr`.

    Raises `MissingConfigurationError` if unset or empty — a
    GitHub-enabled runtime has no safe default token. Never logged,
    never printed, never returned as a plain `str`.
    """
    env = env if env is not None else os.environ
    token = env.get(_ENV_GITHUB_TOKEN)
    if not token:
        raise MissingConfigurationError(
            f"{_ENV_GITHUB_TOKEN} must be set explicitly — there is no default token"
        )
    return SecretStr(token)


class IntentInterpreterProvider(StrEnum):
    """The closed set of `IntentInterpreterPort` providers this platform
    can construct (Batch 23). Exactly one member today — adding a future
    provider (Anthropic, Bedrock) means adding one new member here and
    one new arm in `iac_agent.app.composition.create_intent_interpreter`,
    nothing else. An unrecognized provider string fails at this
    StrEnum's own construction, the same closed-membership mechanism
    `WorkloadType`/`Capability` already rely on — no silent fallback is
    possible by construction."""

    OPENAI = "openai"


@dataclass(frozen=True)
class IntentInterpreterConfig:
    """Non-secret LLM interpreter configuration — always safe to log or
    repr. The credential (an API key, or a future provider's own
    credential chain) is never a field here; see
    `load_openai_api_key_from_env`."""

    provider: IntentInterpreterProvider
    model: str


def load_intent_interpreter_config_from_env(
    env: Mapping[str, str] | None = None,
) -> IntentInterpreterConfig:
    """Build `IntentInterpreterConfig` from environment variables.

    Supported variables:
        IAC_AGENT_LLM_PROVIDER   (required, no default)
        IAC_AGENT_LLM_MODEL      (required, no default)

    Neither has a safe default — this project never silently picks a
    provider or a model. An unrecognized provider string raises
    `MissingConfigurationError`, never a silent fallback to a default
    provider.
    """
    env = env if env is not None else os.environ

    raw_provider = env.get(_ENV_LLM_PROVIDER)
    if not raw_provider:
        raise MissingConfigurationError(
            f"{_ENV_LLM_PROVIDER} must be set explicitly — there is no default LLM provider"
        )
    try:
        provider = IntentInterpreterProvider(raw_provider)
    except ValueError as exc:
        raise MissingConfigurationError(
            f"{_ENV_LLM_PROVIDER} has an unsupported value {raw_provider!r} — supported "
            f"providers: {[p.value for p in IntentInterpreterProvider]}"
        ) from exc

    model = env.get(_ENV_LLM_MODEL)
    if not model:
        raise MissingConfigurationError(
            f"{_ENV_LLM_MODEL} must be set explicitly — there is no default model"
        )

    return IntentInterpreterConfig(provider=provider, model=model)


def load_openai_api_key_from_env(env: Mapping[str, str] | None = None) -> SecretStr:
    """Load the OpenAI API key from `OPENAI_API_KEY`, wrapped in
    `SecretStr`.

    Raises `MissingConfigurationError` if unset or empty — the OpenAI
    adapter has no safe default key. Never logged, never printed, never
    returned as a plain `str`. This fails at composition time, before
    `iac_agent.app.composition.create_intent_interpreter` can even
    construct the adapter — a missing key never surfaces as an
    `IntentInterpreterError` at request time.
    """
    env = env if env is not None else os.environ
    api_key = env.get(_ENV_OPENAI_API_KEY)
    if not api_key:
        raise MissingConfigurationError(
            f"{_ENV_OPENAI_API_KEY} must be set explicitly — there is no default API key"
        )
    return SecretStr(api_key)

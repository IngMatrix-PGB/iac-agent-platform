"""Shared real-tool (Terraform/Checkov) test fixtures (Batch 16.5).

Every real-Terraform integration test previously built its own
credential-free subprocess environment by hand, and every one of those
independent `terraform init` calls re-downloaded its own copy of the
AWS provider binary (~750MB) into that test's own `tmp_path`. Across a
full-suite run this left several GB of duplicate, disposable
`.terraform/providers/...` directories behind under pytest's own
scratch space.

`terraform_test_env` centralizes the fix: one pytest-session-scoped
Terraform provider plugin cache (`TF_PLUGIN_CACHE_DIR`), created
explicitly up front, shared by every real-tool test in the session so
`terraform init` reuses the same downloaded provider binary instead of
fetching its own copy each time. This is provider/plugin *binary*
caching only — it never shares `terraform.tfstate`, a rendered
`tfplan`, or any working directory between test cases; each test still
gets its own isolated `tmp_path` workspace via the ordinary pytest
fixture, exactly as before.

Deliberately NOT the developer's own global
`~/.terraform.d/plugin-cache` — automated tests must never depend on,
or mutate, a directory another developer session might also be using.
`tmp_path_factory` (pytest's own session-scoped temp-directory
mechanism) is used instead, so the cache is disposable pytest-owned
scratch, cleaned up by pytest's normal `tmp_path` retention policy like
any other test artifact — this module never recursively deletes an
arbitrary system temp directory itself.

Concurrency note: Terraform's provider plugin cache is not documented
as safe for unlimited concurrent writers to the *same* uncached
provider version (a well-known upstream caveat). This project's test
suite runs serially (no `pytest-xdist`), so this is a non-issue today;
introducing parallel test execution later would need this reassessed
before reusing this fixture as-is.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

#: The one placeholder-only AWS credential override every real
#: `terraform plan` test already used — centralized here so a new
#: real-tool test can reuse it via `terraform_plan_env_overrides`
#: instead of redefining it locally. Never real credentials.
_PLAN_ENV_OVERRIDES = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}


@pytest.fixture(scope="session")
def tf_plugin_cache_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One pytest-session-owned Terraform provider plugin cache
    directory, created explicitly (Terraform requires the directory to
    already exist). Never the developer's global
    `~/.terraform.d/plugin-cache` or any other shared, mutable,
    non-disposable location."""
    return tmp_path_factory.mktemp("tf-plugin-cache", numbered=False)


@pytest.fixture
def terraform_test_env(tf_plugin_cache_dir: Path) -> dict[str, str]:
    """The base, credential-free environment for a real `terraform`
    subprocess call: PATH/HOME passthrough (required for the `terraform`
    binary to resolve and for Terraform's own CLI config lookup, exactly
    as `TerraformRunner`'s own default env allowlist already requires)
    plus the session-scoped `TF_PLUGIN_CACHE_DIR`. Never includes AWS
    credentials — see `terraform_plan_env_overrides` for the one place
    `terraform plan` needs the placeholder-only credential pair.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TF_PLUGIN_CACHE_DIR": str(tf_plugin_cache_dir),
    }


@pytest.fixture
def terraform_plan_env_overrides(terraform_test_env: dict[str, str]) -> dict[str, str]:
    """`terraform_test_env` plus the existing placeholder-only AWS
    credential override needed for a credential-free `terraform plan`.
    """
    return {**terraform_test_env, **_PLAN_ENV_OVERRIDES}

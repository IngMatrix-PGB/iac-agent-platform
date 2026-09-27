# Batch 30 Docker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the existing FastAPI application as one local container that can plan with Terraform 1.16.1 and Checkov 3.3.13, and can resume a paused HITL checkpoint from a named volume after the first container is removed.

**Architecture:** One multi-stage image runs as uid 10001. `python -m iac_agent.api` calls the existing `serve()` / `create_app` lifespan. Trusted modules come from `IAC_AGENT_TRUSTED_MODULE_ROOT`. The AWS provider is a Terraform filesystem mirror built with `terraform providers mirror`. SQLite lives on volume `iac-agent-state`. Generated workspaces are ephemeral. Gate B serves HTTP through `create_app(holder)` with the Batch 29 fakes so the proof does not call OpenAI or GitHub.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, Terraform 1.16.1, Checkov 3.3.13, Docker, compose.

## Global Constraints

- One image, one container. No sidecar, Docker socket, privileged mode, host network, Kubernetes, ECS, proxy, or authentication.
- Base image `python:3.12-slim-bookworm`, pinned by the digest observed at implementation time. Do not invent a digest in advance.
- Terraform binary exactly `1.16.1`, checksum verified against the official `SHA256SUMS` file. `TerraformRunner` still executes `terraform`.
- Checkov exactly `3.3.13` in `/opt/checkov`. `CheckovAdapter` still executes `checkov`.
- Image install is `.[api,openai,langfuse]`. Observability stays off unless configured. Installing Langfuse does not enable it.
- `httpx` stays on `dev`.
- Defaults: `IAC_AGENT_BIND_HOST=127.0.0.1`, `IAC_AGENT_PORT=8000`. Compose sets bind `0.0.0.0` and publishes `127.0.0.1:8000:8000`.
- `0.0.0.0` inside the container is not authorization.
- User `iac`, uid `10001`. No mode `777`.
- `IAC_AGENT_STATE_DB=/var/lib/iac-agent/state/state.db` on named volume `iac-agent-state`.
- `IAC_AGENT_WORKSPACE_ROOT=/var/lib/iac-agent/workspaces` is not on that volume.
- No secrets in the image, build args, or committed env files.
- Do not broaden `TerraformRunner` environment forwarding. No `apply` or `destroy`. No AWS credentials.
- If a network-disabled `terraform init` still needs `registry.terraform.io`, stop and report. Do not change plan semantics to hide that.
- CI change is only `pytest -m "not real_tool and not real_llm and not docker"` in the deterministic job. No registry push and no Docker build workflow.
- No UI, CORS, or auth.
- No attribution trailers on commits. If `git commit` appends one, create the commit with `git commit-tree` instead of amending.
- Deterministic command after each non-Docker task: `.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q` once the marker exists. Before Task 1, the current command without `and not docker` is still valid.

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml` | `api` extra and `docker` marker |
| `.github/workflows/ci.yml` | exclude `docker` from the deterministic job only |
| `src/iac_agent/api/app.py` | bind host and port |
| `src/iac_agent/api/__main__.py` | `python -m iac_agent.api` |
| `src/iac_agent/app/config.py` | `load_trusted_module_root` |
| `src/iac_agent/graph/modules.py` | `trusted_module_dirs` |
| `src/iac_agent/graph/workflow.py` | call the function instead of `parents[3]` |
| `src/iac_agent/app/composition.py` | pass the resolved mapping |
| `Dockerfile` | multi-stage image |
| `.dockerignore` | build-context exclusions |
| `compose.yaml` | loopback publish and the state volume |
| `.env.example` | names only |
| `tests/unit/api/test_serve_bind.py` | bind defaults |
| `tests/unit/graph/test_trusted_module_root.py` | module root rules |
| `tests/docker/test_image_runtime.py` | Gate A |
| `tests/docker/test_volume_resume.py` | Gate B |
| `docs/api.md`, `docs/roadmap.md` | local container boundary |

---

### Task 1: Docker marker and CI exclusion

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options].markers`)
- Modify: `.github/workflows/ci.yml` (deterministic test step only)
- Create: `tests/docker/test_marker_selected.py`

**Interfaces:**
- Consumes: nothing
- Produces: marker `docker`. Later Docker tests use `@pytest.mark.docker`.

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.docker
def test_docker_marker_is_selected():
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/docker/test_marker_selected.py -q`

Expected: FAIL with an unknown-marker warning treated as an error, or pytest reports `docker` is not a registered marker. If this pytest only warns, the failure condition is the next command still collecting the test:

Run: `.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" --collect-only -q tests/docker/test_marker_selected.py`

Expected before the marker exists: collection error on the unknown marker, or the test is still collected. Either result is the red signal. Do not change any other workflow.

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` markers:

```text
"docker: requires a Docker daemon — excluded from the deterministic CI job (Batch 30).",
```

In `.github/workflows/ci.yml`, change only the deterministic job step to:

```yaml
run: pytest -m "not real_tool and not real_llm and not docker"
```

Leave `pytest -m real_tool` unchanged. Do not add a Docker build job.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest -m docker tests/docker/test_marker_selected.py -q
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" --collect-only -q tests/docker/test_marker_selected.py
```

Expected: the first command passes one test. The second collects nothing from that file.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml tests/docker/test_marker_selected.py
git commit -m "test(docker): exclude daemon tests from deterministic CI"
```

---

### Task 2: API runtime extra

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/unit/api/test_import_isolation.py` (no behavior change; re-run it)

**Interfaces:**
- Consumes: existing pins `fastapi>=0.115,<1` and `uvicorn>=0.32,<1`
- Produces: extra `api` for the image install `.[api,openai,langfuse]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/packaging/test_api_extra.py`:

```python
import tomllib
from pathlib import Path


def test_api_extra_owns_fastapi_and_uvicorn_without_httpx():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    api = data["project"]["optional-dependencies"]["api"]
    dev = data["project"]["optional-dependencies"]["dev"]
    assert any(item.startswith("fastapi>=0.115,<1") for item in api)
    assert any(item.startswith("uvicorn>=0.32,<1") for item in api)
    assert not any(item.startswith("httpx") for item in api)
    assert any(item.startswith("httpx") for item in dev)
    assert any(item.startswith("fastapi") for item in dev)
    assert any(item.startswith("uvicorn") for item in dev)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/packaging/test_api_extra.py -q`

Expected: FAIL because `api` is missing (`KeyError`).

- [ ] **Step 3: Write minimal implementation**

Add:

```toml
api = [
    "fastapi>=0.115,<1",
    "uvicorn>=0.32,<1",
]
```

Leave the same FastAPI and uvicorn pins on `dev`, plus `httpx`, pytest, and ruff. Do not remove them from `dev`. The existing CI lines `pip install -e ".[dev]"` and `.[dev,openai]` must keep installing FastAPI.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/packaging/test_api_extra.py tests/unit/api/test_import_isolation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/unit/packaging/test_api_extra.py
git commit -m "build: add an api extra for the FastAPI runtime"
```

---

### Task 3: Bind, port, and module entrypoint

**Files:**
- Modify: `src/iac_agent/api/app.py`
- Create: `src/iac_agent/api/__main__.py`
- Create: `tests/unit/api/test_serve_bind.py`

**Interfaces:**
- Consumes: `create_app`
- Produces: `bind_host(env) -> str`, `bind_port(env) -> int`, `serve()` using both. `__main__` calls `serve()`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from iac_agent.api.app import bind_host, bind_port


def test_bind_defaults_are_loopback_8000():
    assert bind_host({}) == "127.0.0.1"
    assert bind_port({}) == 8000


def test_bind_reads_container_overrides():
    env = {"IAC_AGENT_BIND_HOST": "0.0.0.0", "IAC_AGENT_PORT": "8000"}
    assert bind_host(env) == "0.0.0.0"
    assert bind_port(env) == 8000


def test_blank_host_is_rejected():
    with pytest.raises(ValueError):
        bind_host({"IAC_AGENT_BIND_HOST": "  "})


def test_invalid_port_is_rejected():
    with pytest.raises(ValueError):
        bind_port({"IAC_AGENT_PORT": "0"})
    with pytest.raises(ValueError):
        bind_port({"IAC_AGENT_PORT": "abc"})
```

Also assert `iac_agent.api.__main__` imports and that its source calls `serve` and does not call `open_intent_application` itself:

```python
import iac_agent.api.__main__ as entry


def test_module_entrypoint_delegates_to_serve():
    assert entry.serve is not None
```

Importing `__main__` must not start uvicorn. The module calls `serve()` only under `if __name__ == "__main__"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_serve_bind.py -q`

Expected: FAIL with `ImportError` for `bind_host` or `__main__`.

- [ ] **Step 3: Write minimal implementation**

```python
def bind_host(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    host = source.get("IAC_AGENT_BIND_HOST", "127.0.0.1").strip()
    if not host:
        raise ValueError("IAC_AGENT_BIND_HOST must not be blank")
    return host


def bind_port(env: Mapping[str, str] | None = None) -> int:
    source = os.environ if env is None else env
    raw = source.get("IAC_AGENT_PORT", "8000").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"IAC_AGENT_PORT must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"IAC_AGENT_PORT must be from 1 to 65535, got {port}")
    return port


def serve() -> None:
    import uvicorn

    uvicorn.run(create_app, factory=True, host=bind_host(), port=bind_port())
```

`src/iac_agent/api/__main__.py`:

```python
from iac_agent.api.app import serve

if __name__ == "__main__":
    serve()
```

Keep `BIND_HOST = "127.0.0.1"` as the documented default constant used by `bind_host` when the variable is absent. Do not change route functions.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_serve_bind.py tests/unit/api/test_app.py -q`

Expected: PASS. `python -m iac_agent.api` is not started here, because that would open the real lifespan.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/api/app.py src/iac_agent/api/__main__.py tests/unit/api/test_serve_bind.py
git commit -m "feat(api): serve from a configurable loopback bind"
```

---

### Task 4: Explicit trusted module root

**Files:**
- Create: `src/iac_agent/graph/modules.py`
- Modify: `src/iac_agent/app/config.py`
- Modify: `src/iac_agent/graph/workflow.py`
- Modify: `src/iac_agent/app/composition.py`
- Create: `tests/unit/graph/test_trusted_module_root.py`
- Modify: `tests/unit/test_resource_registration_consistency.py`
- Modify: `tests/unit/test_composition_registration_consistency.py`
- Modify: `tests/unit/graph/test_workflow_ecr.py`
- Modify: `tests/unit/bootstrap/test_no_self_management.py`

**Interfaces:**
- Consumes: `ResourceType`
- Produces:
  - `load_trusted_module_root(env: Mapping[str, str] | None = None) -> Path`
  - `trusted_module_dirs(root: Path) -> dict[ResourceType, Path]`
  - `default_trusted_module_dirs() -> dict[ResourceType, Path]`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from iac_agent.domain.resource import ResourceType
from iac_agent.graph.modules import trusted_module_dirs


def test_unset_root_points_at_checkout_modules(monkeypatch):
    monkeypatch.delenv("IAC_AGENT_TRUSTED_MODULE_ROOT", raising=False)
    from iac_agent.app.config import load_trusted_module_root

    dirs = trusted_module_dirs(load_trusted_module_root({}))
    assert dirs[ResourceType.SQS].is_dir()
    assert dirs[ResourceType.ECR].name == "ecr"


def test_configured_root_is_used_and_request_text_is_not_an_argument(tmp_path: Path):
    for name in ("sqs", "s3", "dynamodb", "lambda", "api_gateway", "ecr"):
        (tmp_path / "terraform" / "modules" / name).mkdir(parents=True)
    dirs = trusted_module_dirs(tmp_path)
    assert dirs[ResourceType.LAMBDA] == (tmp_path / "terraform" / "modules" / "lambda").resolve()


def test_relative_configured_root_is_rejected(tmp_path: Path):
    from iac_agent.app.config import MissingConfigurationError, load_trusted_module_root

    with pytest.raises(MissingConfigurationError):
        load_trusted_module_root({"IAC_AGENT_TRUSTED_MODULE_ROOT": "terraform"})


def test_missing_module_directory_is_rejected(tmp_path: Path):
    (tmp_path / "terraform" / "modules" / "sqs").mkdir(parents=True)
    with pytest.raises(ValueError):
        trusted_module_dirs(tmp_path)
```

There is no function parameter for a request id or a caller-supplied module path on the HTTP route. The test file does not add one.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/graph/test_trusted_module_root.py -q`

Expected: FAIL with `ModuleNotFoundError: iac_agent.graph.modules`.

- [ ] **Step 3: Write minimal implementation**

`src/iac_agent/graph/modules.py` holds the fixed relative segments:

```python
_MODULE_SEGMENTS: dict[ResourceType, tuple[str, ...]] = {
    ResourceType.SQS: ("terraform", "modules", "sqs"),
    ResourceType.S3: ("terraform", "modules", "s3"),
    ResourceType.DYNAMODB: ("terraform", "modules", "dynamodb"),
    ResourceType.LAMBDA: ("terraform", "modules", "lambda"),
    ResourceType.API_GATEWAY: ("terraform", "modules", "api_gateway"),
    ResourceType.ECR: ("terraform", "modules", "ecr"),
}


def checkout_module_root() -> Path:
    return Path(__file__).resolve().parents[3]


def trusted_module_dirs(root: Path) -> dict[ResourceType, Path]:
    base = root.resolve()
    if not base.is_dir():
        raise ValueError(f"trusted module root is not a directory: {base}")
    resolved: dict[ResourceType, Path] = {}
    for resource_type, segments in _MODULE_SEGMENTS.items():
        candidate = base.joinpath(*segments).resolve()
        candidate.relative_to(base)
        if not candidate.is_dir():
            raise ValueError(f"trusted module directory is missing: {candidate}")
        resolved[resource_type] = candidate
    return resolved


def default_trusted_module_dirs() -> dict[ResourceType, Path]:
    from iac_agent.app.config import load_trusted_module_root

    return trusted_module_dirs(load_trusted_module_root())
```

`load_trusted_module_root` lives in `src/iac_agent/app/config.py`. Unset or empty uses `checkout_module_root()`. Import that function inside `load_trusted_module_root`, not at module scope, so `config` and `modules` do not import each other at import time. A set value must be absolute. It does not create directories.

In `build_iac_workflow`, change `trusted_module_dirs` to default `None`. When it is `None`, call `default_trusted_module_dirs()`. In `build_sqs_workflow`, default `trusted_module_dir` to `None`. Copy `default_trusted_module_dirs()` and replace the SQS entry only when the caller passed a path. Delete `_REPO_ROOT` and the import-time `_DEFAULT_TRUSTED_MODULE_DIRS` dict.

`open_application` passes `trusted_module_dirs=default_trusted_module_dirs()` into `build_sqs_workflow` by passing `trusted_module_dir` only if that remains the wrapper's parameter. The wrapper already overrides SQS from its argument and fills the other types from the default map. Calling `build_sqs_workflow` with no module argument is enough once the default is the function. Pass nothing new if the wrapper resolves the full map itself. Do not read the module root from request JSON.

Update the four unit tests that import `_DEFAULT_TRUSTED_MODULE_DIRS` to call `default_trusted_module_dirs()`. `tests/unit/bootstrap/test_no_self_management.py` must still prove `bootstrap/aws-oidc` is not one of those paths.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/unit/graph/test_trusted_module_root.py tests/unit/test_resource_registration_consistency.py tests/unit/test_composition_registration_consistency.py tests/unit/graph/test_workflow_ecr.py tests/unit/bootstrap/test_no_self_management.py tests/unit/app/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/graph/modules.py src/iac_agent/app/config.py src/iac_agent/graph/workflow.py src/iac_agent/app/composition.py tests/unit/graph/test_trusted_module_root.py tests/unit/test_resource_registration_consistency.py tests/unit/test_composition_registration_consistency.py tests/unit/graph/test_workflow_ecr.py tests/unit/bootstrap/test_no_self_management.py
git commit -m "feat(graph): resolve trusted modules from an explicit root"
```

---

### Task 5: Build-context exclusions and env example

**Files:**
- Create: `.dockerignore`
- Create: `.env.example`
- Create: `tests/unit/docker/test_build_context.py`

**Interfaces:**
- Consumes: nothing
- Produces: the ignore rules and the empty secret template the Dockerfile and compose tasks use

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_dockerignore_keeps_modules_and_drops_secrets():
    text = Path(".dockerignore").read_text()
    for required in (".git", ".venv", ".env", "artifacts/", ".pytest_cache"):
        assert required in text
    assert "terraform/modules" not in text.split()


def test_env_example_has_names_and_no_secret_values():
    text = Path(".env.example").read_text()
    for name in (
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "LANGFUSE_SECRET_KEY",
        "IAC_AGENT_BIND_HOST",
        "IAC_AGENT_TRUSTED_MODULE_ROOT",
        "IAC_AGENT_STATE_DB",
    ):
        assert name in text
    assert "sk-" not in text
    assert "ghp_" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`.dockerignore` excludes `.git`, `.venv`, `venv`, `__pycache__`, `*.py[cod]`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `artifacts/`, `.env`, `.env.*` while un-ignoring `.env.example` if Docker's ignore syntax supports the exception (`!.env.example`), Terraform local state (`.terraform/`, `*.tfstate`, `tfplan*`), and editor files. Do not exclude `terraform/modules`.

`.env.example` sets empty values for the lifespan variables, `IAC_AGENT_OBSERVABILITY=off`, `IAC_AGENT_BIND_HOST=127.0.0.1`, `IAC_AGENT_PORT=8000`, and commented container overrides for the module root, state db, and workspace root. No tokens.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .dockerignore .env.example tests/unit/docker/test_build_context.py
git commit -m "build: ignore local secrets in the Docker context"
```

---

### Task 6: Runtime image and Gate A

**Files:**
- Create: `Dockerfile`
- Create: `tests/docker/test_image_runtime.py`

**Interfaces:**
- Consumes: `python -m iac_agent.api`, `IAC_AGENT_TRUSTED_MODULE_ROOT`, Terraform `1.16.1`, Checkov `3.3.13`
- Produces: local image tag `iac-agent-platform:batch30`

- [ ] **Step 1: Write the failing test**

`tests/docker/test_image_runtime.py` is marked `docker`. It builds `iac-agent-platform:batch30` from the repository root and asserts:

- `docker image inspect` user is `iac` or uid `10001`
- `docker history` and image `Config.Env` do not contain `sk-`, `ghp_`, `github_pat_`, or `AKIA`
- `docker run --rm --entrypoint id iac-agent-platform:batch30 -u` prints `10001`
- `docker run --rm --entrypoint terraform iac-agent-platform:batch30 version` contains `Terraform v1.16.1`
- `docker run --rm --entrypoint checkov iac-agent-platform:batch30 --version` contains `3.3.13`
- inside the container, these paths are writable: `/var/lib/iac-agent/state`, `/var/lib/iac-agent/workspaces`, `/home/iac`, `/tmp`
- these paths are not writable: `/opt/iac-agent/src`, `/opt/checkov`, `/opt/terraform/providers`, and the Terraform binary's directory
- `python -c "import iac_agent.api.app, sys; assert 'langfuse' not in sys.modules"` succeeds with `IAC_AGENT_OBSERVABILITY` unset
- a network-disabled container (`--network none`) can `terraform init -backend=false -input=false` in a writable workspace whose `required_providers` is `hashicorp/aws` `~> 6.0`, using only `/home/iac/.terraformrc`
- that init's stderr does not contain `registry.terraform.io`
- `docker run --network none` with placeholder lifespan env (`GITHUB_*`, `OPENAI_API_KEY=test`, `IAC_AGENT_LLM_PROVIDER=openai`, `IAC_AGENT_LLM_MODEL=test`, observability `off`) eventually answers `GET /health` and `GET /ready` with 200

Use `subprocess.run(["docker", ...])` with `shell=False`. Do not call AWS, OpenAI, Langfuse, or GitHub. Placeholder tokens are the literal `test`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -m docker tests/docker/test_image_runtime.py -q`

Expected: FAIL because `Dockerfile` is absent or the image build fails. This command is not part of the deterministic suite.

- [ ] **Step 3: Write minimal implementation**

Resolve the digest before writing `FROM`:

```bash
docker pull python:3.12-slim-bookworm
docker image inspect python:3.12-slim-bookworm --format '{{index .RepoDigests 0}}'
```

Put that digest in both stages:

```dockerfile
FROM python:3.12-slim-bookworm@sha256:<observed-digest> AS builder
```

Do not reuse a digest copied from memory if `inspect` shows a different one.

Builder stage:

- Install `ca-certificates` and `curl` only in this stage.
- Download `https://releases.hashicorp.com/terraform/1.16.1/terraform_1.16.1_linux_${TARGETARCH}.zip` and `terraform_1.16.1_SHA256SUMS`.
- `sha256sum -c` the zip against the matching line. Fail the build if it does not match.
- Create `/opt/iac-agent/.venv` and `pip install --no-cache-dir ".[api,openai,langfuse]"` from the copied source tree. The install must remain editable or otherwise leave `workflow.py` at `/opt/iac-agent/src/iac_agent/graph/workflow.py`.
- Create `/opt/checkov` with `python -m venv` and `pip install checkov==3.3.13`. Symlink `/opt/checkov/bin/checkov` onto a path that will be on `PATH`.
- Run `terraform providers mirror -platform=linux_${TARGETARCH}` from a throwaway directory whose only Terraform configuration is:

```hcl
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
```

Write the mirror to `/opt/terraform/providers`. Write `/home/iac/.terraformrc`:

```hcl
provider_installation {
  filesystem_mirror {
    path    = "/opt/terraform/providers"
    include = ["registry.terraform.io/hashicorp/aws"]
  }
  direct {
    exclude = ["registry.terraform.io/hashicorp/aws"]
  }
}
```

Runtime stage copies the venvs, Terraform binary, `/opt/iac-agent` source and `terraform/modules`, the provider mirror, and `/home/iac/.terraformrc`. It does not copy curl. It creates uid/gid `10001`, `HOME=/home/iac`, the state and workspace directories owned by `iac`, and `USER iac`.

Image `ENV` sets bind `0.0.0.0`, port `8000`, module root `/opt/iac-agent`, state db, workspace root, and `IAC_AGENT_OBSERVABILITY=off`. It sets no secrets.

`CMD` is `/opt/iac-agent/.venv/bin/python -m iac_agent.api`.

`HEALTHCHECK` uses that interpreter and `urllib.request` against `http://127.0.0.1:8000/health`.

If `--network none` init still contacts the registry or exits non-zero, stop this task and report the Terraform output. Do not add `TF_CLI_CONFIG_FILE` to `TerraformRunner` and do not change `render_versions_tf`.

If the lifespan opens a socket during construction under `--network none`, stop and report that stack. Do not add a fake-interpreter switch to production `serve()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -m docker tests/docker/test_image_runtime.py -q`

Expected: PASS. Then run the deterministic suite from the Global Constraints and confirm the Docker test was not collected.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile tests/docker/test_image_runtime.py
git commit -m "build: add the local FastAPI runtime image"
```

---

### Task 7: Compose file

**Files:**
- Create: `compose.yaml`
- Modify: `tests/unit/docker/test_build_context.py`

**Interfaces:**
- Consumes: image build, volume name `iac-agent-state`
- Produces: the supported local run command `docker compose up`

- [ ] **Step 1: Write the failing test**

Extend `tests/unit/docker/test_build_context.py` to parse `compose.yaml` as YAML and assert:

- one service
- port mapping `127.0.0.1:8000:8000`
- `IAC_AGENT_BIND_HOST` is `0.0.0.0`
- `IAC_AGENT_STATE_DB` is `/var/lib/iac-agent/state/state.db`
- `IAC_AGENT_WORKSPACE_ROOT` is `/var/lib/iac-agent/workspaces`
- `IAC_AGENT_TRUSTED_MODULE_ROOT` is `/opt/iac-agent`
- named volume `iac-agent-state` is mounted at `/var/lib/iac-agent/state`
- no service image is `postgres`, `redis`, or `localstack`
- no volume source is `/var/run/docker.sock`
- `network_mode` is not `host`
- `privileged` is not true
- a stop grace period is present

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`

Expected: FAIL because `compose.yaml` is missing.

- [ ] **Step 3: Write minimal implementation**

`compose.yaml` builds `.`, names the service `iac-agent`, publishes only `127.0.0.1:8000:8000`, mounts `iac-agent-state`, sets the paths and bind host from Task 6, uses `env_file: .env` without committing `.env`, and sets `stop_grace_period: 30s`. Do not put secret values in the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`

Expected: PASS. Do not start the container in this task.

- [ ] **Step 5: Commit**

```bash
git add compose.yaml tests/unit/docker/test_build_context.py
git commit -m "build: publish the local API on host loopback"
```

---

### Task 8: Gate B container replacement

**Files:**
- Create: `tests/docker/harness.py`
- Create: `tests/docker/test_volume_resume.py`

**Interfaces:**
- Consumes: image `iac-agent-platform:batch30`, `create_app`, `open_sqlite_checkpointer`, `build_iac_workflow`, `default_trusted_module_dirs`
- Produces: proof that volume `iac-agent-state` survives `docker rm` of container A

- [ ] **Step 1: Write the failing test**

`tests/docker/harness.py` is the server used only by this test. It builds the graph the way `tests/integration/test_api_fresh_process.py` does, with these differences:

- checkpointer path is `IAC_AGENT_STATE_DB`
- workspace root is `IAC_AGENT_WORKSPACE_ROOT`
- `trusted_module_dirs` comes from `default_trusted_module_dirs()`
- Terraform and Checkov are the real `TerraformRunner()` and `CheckovAdapter()`
- interpreter is the fake worker-payload interpreter from that test
- source control returns `PullRequestResult(number=7, url="https://example.invalid/pull/7", branch="iac-agent/req-docker-fresh", base_branch="main")` and records calls in `/var/lib/iac-agent/state/publisher-calls` so container B can see the count on the volume
- `create_app(holder)` is served with uvicorn on `0.0.0.0` port `8000`
- the file does not import `iac_agent.git.github`

`tests/docker/test_volume_resume.py` is marked `docker`. It creates a fresh named volume, runs container A with `--entrypoint` set to the venv Python and the harness bind-mounted at `/tmp/harness.py`, posts `req-docker-fresh`, asserts `201` and `awaiting_approval`, then `docker rm -f` container A. It asserts `docker inspect` of A fails and that no workspace volume was mounted. It starts container B the same way on the same volume. B's interpreter raises if called. B's publisher starts from the recorded call count. `GET /api/v1/requests/req-docker-fresh` is `200` `awaiting_approval`. `GET /api/v1/requests/req-missing` is `404` `request_not_found` and the body does not contain `pending`. `POST` approval `approve` returns `200`, `pr_created`, and `workflow.pull_request == {"url": "https://example.invalid/pull/7"}`. The publisher record increases by one. The test deletes the volume at the end.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -m docker tests/docker/test_volume_resume.py -q`

Expected: FAIL until the harness and the image from Task 6 can complete the sequence.

- [ ] **Step 3: Write minimal implementation**

Implement the harness and the test. Do not add a production environment switch that disables GitHub or OpenAI. Do not persist `/var/lib/iac-agent/workspaces`. Container B must be a different container id from A.

If resume fails because the checkpoint's workspace path is required, stop and report that evidence. Do not persist the workspace to make the test pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -m docker tests/docker/test_volume_resume.py -q`

Expected: PASS, and the test process log shows no call to `api.github.com`, `api.openai.com`, `cloud.langfuse.com`, or an AWS endpoint.

- [ ] **Step 5: Commit**

```bash
git add tests/docker/harness.py tests/docker/test_volume_resume.py
git commit -m "test(docker): resume HITL from a replacement container"
```

---

### Task 9: Document the local container boundary

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/roadmap.md`

**Interfaces:**
- Consumes: the closed design
- Produces: operator-facing description of the loopback container

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/docker/test_build_context.py`:

```python
def test_api_doc_states_container_bind_is_not_authorization():
    text = Path("docs/api.md").read_text()
    assert "127.0.0.1:8000:8000" in text
    assert (
        "0.0.0.0 inside the container is network binding, "
        "not authentication or authorization."
    ) in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py::test_api_doc_states_container_bind_is_not_authorization -q`

Expected: FAIL because `docs/api.md` does not yet mention `127.0.0.1:8000:8000`.

- [ ] **Step 3: Write minimal implementation**

In `docs/api.md`, state that `python -m iac_agent.api` serves the existing app, the default bind is `127.0.0.1:8000`, and compose publishes `127.0.0.1:8000:8000` to a container bound at `0.0.0.0:8000`. Include the sentence: `0.0.0.0 inside the container is network binding, not authentication or authorization.` State that the API is still not approved for public Internet exposure, that SQLite on `iac-agent-state` is the durable HITL store, and that generated workspaces are ephemeral. State that Batch 31 is the operator UI and this batch did not add one.

In `docs/roadmap.md`, replace the sentence that says Docker is not started with a pointer to this design and to `compose.yaml`. Leave UI and authentication described as not started.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q
.venv/bin/python -m ruff check .
git diff --check
.venv/bin/python -m pytest -m docker -q
```

Expected: the deterministic suite passes and does not collect `tests/docker/test_image_runtime.py` or `tests/docker/test_volume_resume.py`. The `docker` command passes both Gate A and Gate B. Ruff and `git diff --check` pass.

- [ ] **Step 5: Commit**

```bash
git add docs/api.md docs/roadmap.md tests/unit/docker/test_build_context.py
git commit -m "docs: document the local Docker runtime boundary"
```

---

## Self-review

| Closed decision | Task |
|---|---|
| One image, Terraform 1.16.1, Checkov 3.3.13, modules | 6 |
| Digest pinned from `docker image inspect` | 6 |
| Multi-stage, no curl in the runtime stage | 6 |
| `api` extra, `.[api,openai,langfuse]`, httpx stays on dev | 2 |
| Checkov virtualenv, bare `checkov` | 6 |
| Official Terraform zip and SHA256SUMS | 6 |
| `terraform providers mirror`, stop if registry is still required | 6 |
| `IAC_AGENT_TRUSTED_MODULE_ROOT` | 4 |
| `python -m iac_agent.api` | 3 |
| Bind defaults and compose loopback publish | 3, 7 |
| uid 10001 and writable paths | 6 |
| State directory volume, ephemeral workspaces | 7, 8 |
| Secrets only at runtime | 5, 6 |
| No AWS credential forwarding | 6 |
| `/health` healthcheck, `/ready` unchanged | 6 |
| SIGTERM via uvicorn | 6, no new signal code |
| Minimal compose | 7 |
| `.dockerignore` | 5 |
| `docker` marker and one CI expression | 1 |
| Gate A | 6 |
| Gate B fake publisher, no real GitHub | 8 |
| No auth, no UI | no task adds them |
| Eager OpenAI/GitHub startup left as debt | no task refactors the lifespan |

No task rewrites `TerraformRunner` or `CheckovAdapter`. No task adds a production fake-interpreter switch.

## Planning-turn validation

This plan was written before any Docker implementation. Do not record Docker tests as passed in this commit. The first implementation turn starts at Task 1.

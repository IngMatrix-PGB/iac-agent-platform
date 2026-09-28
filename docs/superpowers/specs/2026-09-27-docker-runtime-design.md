# Batch 30 — Docker runtime packaging

Closed design. Implementation is a later turn. This document does not add a Dockerfile, compose file, or production code.

Verified baseline: `origin/main` is `ab39fca2af6850e58ce285776bc80da08f3e8a19`, the merge of pull request #12. `docs/api.md` and `src/iac_agent/api/app.py` are on that commit.

## 1. Current code this design starts from

`serve()` in `src/iac_agent/api/app.py` runs uvicorn on the constant `127.0.0.1` port `8000`. There is no `python -m iac_agent.api` module. The only console script is the CLI.

The lifespan calls `open_intent_application`. That opens one SQLite checkpointer at `IAC_AGENT_STATE_DB` (default `<IAC_AGENT_WORKSPACE_ROOT>/state.db`, workspace default `artifacts`) and builds the graph with `TerraformRunner()`, `CheckovAdapter()`, and `GitHubSourceControl`. Missing GitHub or OpenAI configuration raises `MissingConfigurationError` before the process serves. `/health` is a local `200`. `/ready` is `200` only when the holder exists. Observability defaults to off. The Langfuse SDK is imported only inside its factory.

`TerraformRunner` executes the bare command `terraform`. `CheckovAdapter` executes the bare command `checkov`. Neither forwards the process environment beyond `PATH` and `HOME`. `plan` adds `AWS_ACCESS_KEY_ID=test` and `AWS_SECRET_ACCESS_KEY=test`. There is no `apply` or `destroy`. GitHub publication uses `urllib`, not a `git` binary.

`source_control` publishes `generated_files` from the checkpoint. Resume after `awaiting_approval` does not rerun Terraform and does not need the original workspace directory.

Trusted modules are resolved today by `_REPO_ROOT = Path(__file__).resolve().parents[3]` in `src/iac_agent/graph/workflow.py`. From a source checkout that parent is the repository root. `IacRenderer` turns those directories into relative module sources with `os.path.relpath`. A site-packages install points `parents[3]` at the wrong directory. CI already pins Terraform `1.16.1` and Checkov `3.3.13`. Python is `>=3.12,<3.13`. FastAPI and uvicorn are on the `dev` extra. `terraform/modules/lambda/fixtures/placeholder.zip` is part of the Lambda module.

## 2. Closed architecture

One application image. One application container. The image contains Python 3.12, the application, Terraform 1.16.1, Checkov 3.3.13 in its own virtualenv, and the trusted Terraform modules.

Out of scope: Terraform or Checkov sidecars, Docker-in-Docker, a Docker socket, Kubernetes, ECS, cloud deployment, a reverse proxy, and authentication.

`0.0.0.0` inside the container is network binding. It is not authentication or authorization. Compose publishes only `127.0.0.1:8000:8000`. This runtime is for local development. It is not approved for public Internet exposure.

Batch 31 is the operator web UI. It will call the Batch 29 API after this runtime is merged. This batch adds no frontend and no CORS.

The centralized registry/catalog ADR stays closed. Packaging several modules into an image is not a reopening criterion.

## 3. Image and dependencies

Base image: `python:3.12-slim-bookworm`. Implementation resolves the real digest with `docker image inspect` and pins `FROM` to it. This design does not invent a digest.

Multi-stage build. Download and compile tools stay in earlier stages. The runtime stage contains the application virtualenv, the Checkov virtualenv, the Terraform binary, the trusted modules, the provider mirror, and the system libraries those binaries need.

New extra `api`:

- `fastapi>=0.115,<1`
- `uvicorn>=0.32,<1`

`httpx` stays on `dev`. The image installs `.[api,openai,langfuse]` and does not install `dev`. Installing the Langfuse package does not enable telemetry. `IAC_AGENT_OBSERVABILITY` remains default `off`. The existing CI install commands keep working, so `dev` continues to list FastAPI and uvicorn beside the new extra. The image does not use `dev`.

Checkov `3.3.13` is installed in `/opt/checkov`. A `checkov` executable on `PATH` points at that environment. `CheckovAdapter` is not rewritten.

Terraform `1.16.1` comes from the official HashiCorp zip for the image OS and architecture. The build downloads `terraform_1.16.1_SHA256SUMS` and verifies the zip against that file. It does not copy an unverified binary into the runtime stage. `TerraformRunner` is not rewritten.

## 4. Terraform provider

Normal `terraform init` and `plan` must not download an already-prepared AWS provider from `registry.terraform.io`.

The build uses the official `terraform providers mirror` command against a throwaway configuration whose provider constraint matches `render_versions_tf`: `hashicorp/aws` `~> 6.0`, for the image's `os_arch`. The mirror is stored at `/opt/terraform/providers` and is not writable by uid `10001`.

The runtime CLI config is `/home/iac/.terraformrc`, because `TerraformRunner` passes `HOME` and does not pass `TF_CLI_CONFIG_FILE`. The file uses Terraform's `provider_installation` filesystem mirror and excludes `registry.terraform.io/hashicorp/aws` from `direct`. That is Terraform's own installation config, not a custom installer. No AWS credentials are present. The build does not run `apply` or `destroy`.

If a network-disabled `terraform init` still requires the registry, or a read-only mirror cannot satisfy `~> 6.0` without changing plan semantics, implementation stops and reports that blocker. It does not widen `TerraformRunner` environment forwarding and it does not change the provider constraint.

## 5. Trusted module root

`parents[3]` is not the container contract.

Add an explicit root, read once at process start from `IAC_AGENT_TRUSTED_MODULE_ROOT`. Docker sets it to `/opt/iac-agent`. When the variable is unset, the default remains the source checkout that contains `terraform/modules`, so local development and existing tests keep working without new environment variables.

`trusted_module_dirs(root)` maps each `ResourceType` to `root / "terraform" / "modules" / <that type's directory>`. The directory list stays in code. A missing directory is an error. Each result must stay inside `root`. HTTP requests have no field for this path. Request text cannot select a module root.

Production files for this boundary:

- `src/iac_agent/graph/modules.py` — `trusted_module_dirs(root: Path)` and the checkout default
- `src/iac_agent/app/config.py` — `load_trusted_module_root(env) -> Path`
- `src/iac_agent/graph/workflow.py` — `build_iac_workflow` and `build_sqs_workflow` call that function when the caller does not pass directories
- `src/iac_agent/app/composition.py` — passes the resolved mapping into the graph

Callers that import `_DEFAULT_TRUSTED_MODULE_DIRS` move to the function. The registration tests still prove every `ResourceType` has a real directory.

## 6. Process entry, bind, and shutdown

`src/iac_agent/api/__main__.py` calls `serve()`. The command is `python -m iac_agent.api`. It uses `create_app` and the existing lifespan. It is not a second API.

`serve()` reads:

| Variable | Default outside Docker | Container |
|---|---|---|
| `IAC_AGENT_BIND_HOST` | `127.0.0.1` | `0.0.0.0` |
| `IAC_AGENT_PORT` | `8000` | `8000` |

An invalid port fails startup. uvicorn's normal `SIGTERM` handling runs the lifespan to exit, which closes the SQLite checkpointer. No custom signal handler unless a test proves the connection stays open.

## 7. Filesystem, persistence, and user

User `iac`, uid `10001`. The container is not privileged, does not mount the Docker socket, and does not use host networking.

| Path | Contents | Writable by uid 10001 |
|---|---|---|
| `/opt/iac-agent` | application tree and `terraform/modules`, including `placeholder.zip` | no |
| `/opt/checkov` | Checkov virtualenv | no |
| `/opt/terraform/providers` | provider mirror | no |
| Terraform binary | official 1.16.1 binary | no |
| `/home/iac` | `HOME` and `.terraformrc` | yes |
| `/var/lib/iac-agent/state` | SQLite directory | yes |
| `/var/lib/iac-agent/workspaces` | generated workspaces | yes |
| `/tmp` | temporary files | yes |

No mode `777`.

`IAC_AGENT_STATE_DB=/var/lib/iac-agent/state/state.db`. Compose mounts named volume `iac-agent-state` on the directory, so `state.db-wal` and `state.db-shm` stay with the database. The database must not live only in the container writable layer.

`IAC_AGENT_WORKSPACE_ROOT=/var/lib/iac-agent/workspaces` is ephemeral. It is not on `iac-agent-state`. Removing the container deletes the workspace. The checkpoint remains. Gate B proves resume without that workspace.

## 8. Secrets

Secrets are runtime environment only. The image build does not `COPY` `.env`, use `ARG` or `ENV` for real secrets, or commit a populated secret file.

`.env.example` lists names and empty placeholders. Required by the current lifespan before `/ready` can be true:

- `GITHUB_OWNER`
- `GITHUB_REPOSITORY`
- `GITHUB_COMMIT_AUTHOR_NAME`
- `GITHUB_COMMIT_AUTHOR_EMAIL`
- `GITHUB_TOKEN`
- `IAC_AGENT_LLM_PROVIDER`
- `IAC_AGENT_LLM_MODEL`
- `OPENAI_API_KEY`

Optional: `GITHUB_BASE_BRANCH` (`main`), `IAC_AGENT_OBSERVABILITY` (`off`), Langfuse keys and `LANGFUSE_BASE_URL` only when observability is `langfuse`.

No AWS profile, SSO, OIDC, access key, or role is part of this image. Credential-free plan behavior stays as it is.

Eager GitHub and OpenAI configuration at startup is technical debt. Batch 30 does not make that initialization lazy.

Docker logs stay on uvicorn's access line. They do not record bodies, prompts, Terraform source, plan JSON, checkpoints, or environment values. Batch 28 telemetry and the Batch 29 HTTP projection are unchanged. No HTTP telemetry middleware.

## 9. Health and compose

The image healthcheck requests `GET /health` on the container loopback. It does not call AWS, OpenAI, Langfuse, GitHub, or the Terraform Registry. `/ready` keeps the Batch 29 meaning and is not redesigned.

`compose.yaml` builds the image, publishes `127.0.0.1:8000:8000`, sets `IAC_AGENT_BIND_HOST=0.0.0.0`, sets the state and workspace paths and the trusted-module root, mounts `iac-agent-state`, reads runtime environment from the operator, and uses a normal stop grace period. It does not add a database, Redis, proxy, Langfuse server, LocalStack, or an AWS emulator.

`.dockerignore` excludes `.git`, virtualenvs, caches, local `artifacts/`, local SQLite and Terraform state, `.env` and secret-bearing env files, and editor metadata. It does not exclude `terraform/modules/`.

## 10. Tests and CI

New marker: `docker`.

The deterministic CI command becomes:

```bash
pytest -m "not real_tool and not real_llm and not docker"
```

That is the only CI change. No image publish, GHCR, ECR, Docker build workflow, signing, SBOM, or vulnerability scanner.

`pyproject.toml` declares the marker. `tests/docker/` holds the daemon tests. The existing in-process proof `tests/integration/test_api_fresh_process.py` stays unmarked.

### Gate A

The image builds. The process uid is `10001`. With placeholder configuration that satisfies the lifespan, `/health` and `/ready` return 200. `terraform version` is `1.16.1`. `checkov --version` is `3.3.13`. Startup with observability unset does not import Langfuse. A credential-free plan uses the baked provider and does not contact `registry.terraform.io`. Trusted modules resolve from `IAC_AGENT_TRUSTED_MODULE_ROOT`. The state and workspace directories are writable by uid `10001`. `/opt/iac-agent`, `/opt/checkov`, the provider mirror, and the Terraform binary are not. Image config and history contain no real secret. The acceptance test does not call AWS, OpenAI, Langfuse Cloud, or GitHub.

### Gate B

Container A uses the production image, the named volume, and a test harness mounted only for the test. The harness calls `create_app` with the same fakes as the Batch 29 fresh-process test: fake interpreter, fake source control, and the image's Terraform, Checkov, module root, and SQLite path. It does not import the GitHub adapter.

A creates `req-docker-fresh`, reaches `awaiting_approval`, and writes the checkpoint on the volume. A is removed. Its writable layer and workspace are not kept. Container B is a new process with the same image and the same volume. `GET` returns `awaiting_approval`. Approve resumes. The fake publisher is called once. The outcome is `pr_created` and the URL is `https://example.invalid/pull/7`. There is no real GitHub mutation, OpenAI call, Langfuse Cloud call, AWS call, or `terraform apply` / `destroy`.

The production lifespan is not the Gate B server. It constructs the real OpenAI interpreter and the real GitHub adapter, which this proof must not call. The harness is a test file. It is not a second API and it is not installed as the image command.

## 11. Non-goals

UI, authentication, CORS, JWT, OAuth, API keys, KMS, CloudFront, ECS, Fargate, ECR publishing, Kubernetes, Helm, a registry or catalog, new AWS resources, a Langfuse Cloud smoke test, `terraform apply`, and `terraform destroy`.

## 12. Technical debt left in place

The lifespan still requires GitHub and OpenAI settings before `/health` is served, even when a request never publishes and observability is off. A missing variable fails startup. It does not return `/ready` 503. Batch 30 documents that and does not split it.

`HOME` is writable, so the process user can replace `/home/iac/.terraformrc`. The provider mirror directory is not writable. HTTP clients cannot set either path. Batch 30 does not take write access to `HOME` away, because Terraform's CLI config is discovered through `HOME`.

## 13. Theoretical implementation files

Production:

- `Dockerfile`
- `.dockerignore`
- `compose.yaml`
- `.env.example`
- `src/iac_agent/api/__main__.py`
- `src/iac_agent/api/app.py` (bind and port only)
- `src/iac_agent/graph/modules.py`
- `src/iac_agent/app/config.py`
- `src/iac_agent/graph/workflow.py`
- `src/iac_agent/app/composition.py`
- `pyproject.toml` (`api` extra and `docker` marker)
- `.github/workflows/ci.yml` (the one pytest expression)
- `docs/api.md`
- `docs/roadmap.md`

Tests:

- `tests/unit/api/test_serve_bind.py`
- `tests/unit/graph/test_trusted_module_root.py`
- `tests/docker/test_image_runtime.py`
- `tests/docker/test_volume_resume.py`

Unit tests that import `_DEFAULT_TRUSTED_MODULE_DIRS` are updated to the new function in the same change that introduces it.

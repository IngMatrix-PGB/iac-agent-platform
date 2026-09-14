# Application Composition

## Why a composition root

Through Batch 14, every test constructed the renderer, `TerraformRunner`,
`CheckovAdapter`, `GitHubSourceControl`, and the SQLite checkpointer
directly, then wired them into `build_sqs_workflow` itself. Batch 15
adds the one place a real caller (a future FastAPI handler, a CLI, a
script) does that instead: `iac_agent.app`.

```
iac_agent.app.config        — typed, non-secret configuration + env loaders
iac_agent.app.composition   — constructs the real adapters + compiled graph
iac_agent.app.service       — Phase1Application: submit / resume / get_state
```

No domain module and no LangGraph node reads `os.environ` or
constructs a concrete adapter itself — `iac_agent.app.config` is the
only place environment variables are read, and
`iac_agent.app.composition` is the only place `TerraformRunner`,
`CheckovAdapter`, `GitHubSourceControl`, and the SQLite checkpointer are
instantiated together.

## Configuration boundary

`ApplicationConfig` (`iac_agent.app.config`) is a frozen dataclass
holding only non-secret settings — always safe to log or repr:

```python
ApplicationConfig(
    workspace_root: Path,
    state_db_path: Path,
    terraform_module_path: Path,
    github_owner: str,
    github_repository: str,
    github_base_branch: str = "main",
)
```

`load_application_config_from_env(env=None)` reads:

| Variable | Required? | Default |
|---|---|---|
| `IAC_AGENT_WORKSPACE_ROOT` | no | `artifacts` |
| `IAC_AGENT_STATE_DB` | no | `<workspace_root>/state.db` |
| `GITHUB_OWNER` | **yes** | none |
| `GITHUB_REPOSITORY` | **yes** | none |
| `GITHUB_BASE_BRANCH` | no | `main` |

`GITHUB_OWNER` and `GITHUB_REPOSITORY` have no default and raise
`MissingConfigurationError` if absent — this project never silently
defaults to a real user or repository.

## The GitHub token stays outside `ApplicationConfig`

The token is never a field on `ApplicationConfig` — it is loaded
separately by `load_github_token_from_env()`, wrapped in Pydantic's
`SecretStr` (already a transitive dependency, so no new dependency was
added solely for secret wrapping). `SecretStr.__repr__`/`__str__` never
reveal the value; only `.get_secret_value()` does, and that is called
exactly once, at the point `iac_agent.app.composition.open_application`
constructs `GitHubSourceControl`. The token is never written into
`ApplicationConfig`, `WorkflowState`, `WorkflowView`, a log line, or
`state.db`.

## `state.db` naming convention

Batch 15 adopts `state.db` as the canonical example/application
filename for the SQLite checkpoint database, replacing the earlier,
unnecessarily verbose test/example filename used through Batch 14. This
is a naming convention only:
`iac_agent.persistence.checkpoints.open_sqlite_checkpointer` still
requires an explicit `Path` and hardcodes no filename itself — a caller
always states exactly where the database lives. When the application
layer's own default applies, it resolves under the configured
`workspace_root` (`<workspace_root>/state.db`), never scattered
unpredictably into whatever directory happened to invoke Python.

No database schema migration was implemented or is needed — this is a
filename cleanup only, and there are no deployed users of an older
filename to migrate.

## Composition lifecycle

`open_application(config, *, github_token, github_transport=None)` is a
context manager:

```python
with open_application(config, github_token=token) as application:
    app = Phase1Application.from_application(application)
    ...
# the underlying SQLite connection is guaranteed closed here, even on error
```

`Application` (the yielded object) holds only `config` and the
compiled `graph` — never the raw SQLite connection, never the GitHub
token. `github_transport` is an optional test-only seam (defaults to
`GitHubSourceControl`'s real `UrllibHttpTransport`); production callers
never pass it.

There are no global singletons anywhere in this layer
(`GLOBAL_GRAPH`/`GLOBAL_DB`/`GLOBAL_GITHUB_CLIENT`/`GLOBAL_CONFIG` do
not exist) — every `Application`/`Phase1Application` is constructed
independently, so two instances (even against different databases in
the same process) never share state.

## `Phase1Application`: submit / resume / get_state

```python
app = Phase1Application.from_application(application)

app.submit(request_id="req-001", spec=my_spec)  # -> WorkflowView
app.resume("req-001", ApprovalDecision.APPROVE)  # -> WorkflowView
app.get_state("req-001")  # -> WorkflowView, read-only
```

- `submit` invokes the compiled graph for a new request, using
  `workflow_config(request_id)` — for a secure valid request, the
  returned view's `workflow_status` is `AWAITING_APPROVAL`.
- `resume` supplies a human decision through the real LangGraph resume
  API (`Command(resume=...)`) — it never bypasses the approval
  interrupt.
- `get_state` only reads the current checkpoint (`graph.get_state`). It
  never executes a node, never resumes an interrupt, and never
  triggers a GitHub mutation — the same guarantee already proven at the
  graph level in Batches 12-14.

## `WorkflowView`: a bounded result, never a raw state dump

Every method returns a `WorkflowView`, not `WorkflowState`:

```python
WorkflowView(
    request_id,
    workflow_status,
    current_stage,
    resource_name,
    security_status,
    plan_summary,
    approval_decision,
    pull_request,
    error,
)
```

It deliberately excludes the workspace path, the GitHub token, raw
Terraform plan JSON, raw Checkov data, exception objects, and any
SQLite handle — `plan_summary` and `error` are the same already-safe,
already-normalized domain objects (`PlanSummary`, `WorkflowError`)
proven safe in earlier batches, not new raw data.

## No FastAPI, no CLI yet

`Phase1Application` is the boundary a future FastAPI adapter will call
— this batch adds no HTTP endpoints and no production CLI. The one
exception is `scripts/live_github_smoke.py`, a one-off, explicitly
confirmed script used only for this batch's single controlled live
GitHub verification (see `docs/source-control.md`).

## Still no Terraform apply

Nothing in this layer changes that: `TerraformRunner` still has no
`apply` method, and a GitHub pull request remains Phase 1's terminal
artifact.

## Live validation record

`scripts/live_github_smoke.py` was run once, through
`Phase1Application` end to end (`submit` → `resume(APPROVE)`), against
the project's real repository. It reached `PR_CREATED` with a real,
still-open pull request. See `docs/source-control.md` for the full
record (request ID, branch convention, artifact-exclusion result). No
AWS resource was ever created — the plan stayed credential-free — and
`state.db` for that run was independently checked afterward to contain
no token and no raw Terraform/Checkov JSON.

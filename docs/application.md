# Application composition

## Why a composition root

`iac_agent.app` is where a real caller wires the renderer,
`TerraformRunner`, `CheckovAdapter`, source control, and the SQLite
checkpointer. Callers are the HTTP API (`docs/api.md`), the CLI, and
tests. Domain modules and graph nodes do not construct those adapters
and do not read `os.environ`.

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
    github_owner: str,
    github_repository: str,
    github_commit_author_name: str,
    github_commit_author_email: str,
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
| `GITHUB_COMMIT_AUTHOR_NAME` | **yes** | none |
| `GITHUB_COMMIT_AUTHOR_EMAIL` | **yes** | none |
| `GITHUB_BASE_BRANCH` | no | `main` |

`load_application_config_from_env` raises `MissingConfigurationError`
when `GITHUB_OWNER`, `GITHUB_REPOSITORY`, or either commit-author
variable is absent. There is no silent default owner, repository, or
commit identity. The commit-author fields are public metadata. Unlike
the token, they live on `ApplicationConfig`, and `GitHubSourceControl`
sends them on every generated commit.

The operator runtime may omit the whole GitHub group. A partial group
fails startup. An omitted group does not publish. See `docs/api.md`.

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

The application default filename is `state.db`.
`open_sqlite_checkpointer` still requires an explicit path and does not
hardcode that name. The default location is
`<workspace_root>/state.db`. The same file holds `request_index`. See
`docs/persistence.md`.

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

## `IacApplication`: submit / resume / read

```python
app = IacApplication.from_application(application)

app.submit(request_id="req-001", spec=my_spec)  # -> WorkflowView
app.resume("req-001", ApprovalDecision.APPROVE)  # -> WorkflowView
app.get_state("req-001")  # -> WorkflowView, read-only
```

`spec` is an `IacRequestSpec`: any supported resource or composition,
not SQS alone. `Phase1Application` is the same class. The graph is
`build_iac_workflow`. Trusted module directories cover every supported
resource and composition.

- `submit` invokes the compiled graph for a new request, using
  `workflow_config(request_id)` — for a secure valid request, the
  returned view's `workflow_status` is `AWAITING_APPROVAL`.
- `resume` supplies a human decision through the real LangGraph resume
  API (`Command(resume=...)`) — it never bypasses the approval
  interrupt.
- `get_state` only reads the current checkpoint (`graph.get_state`). It
  never executes a node, never resumes an interrupt, and never
  triggers a GitHub mutation — the same guarantee already proven at the
  graph level.

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
already used by the workflow, not a raw plan or a raw scanner dump.

## CLI and HTTP

The HTTP API is a FastAPI adapter over `IntentResolutionService` and
`IacApplication`. Its routes, operator secret, and capability rules are
`docs/api.md`.

The CLI is a thin stdlib-`argparse` client of the same boundary:

```
iac-agent propose "<natural language request>" [--request-id ID]
iac-agent resume  REQUEST_ID --approve|--reject
```

It calls only `IntentResolutionService.submit` and
`IacApplication.resume`/`get_state` — never LangGraph, Terraform,
Checkov, or GitHub APIs directly — and never runs `terraform apply`.
Required environment variables (names only; see
`iac_agent.app.config` for what each loads):
`GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`,
`GITHUB_COMMIT_AUTHOR_EMAIL`, `GITHUB_TOKEN`, `IAC_AGENT_LLM_PROVIDER`,
`IAC_AGENT_LLM_MODEL`, `OPENAI_API_KEY`, and the optional
`IAC_AGENT_WORKSPACE_ROOT` / `IAC_AGENT_STATE_DB`. See
`docs/real-llm-intent-interpreter.md` for the LLM variables' own
scope and privacy boundary. `scripts/live_github_smoke.py` remains a
separate, one-off script — the CLI does not extend it.

## No Terraform apply

`TerraformRunner` has no `apply` method and no `destroy` method. A
GitHub pull request is the terminal artifact. See
`docs/source-control.md`.

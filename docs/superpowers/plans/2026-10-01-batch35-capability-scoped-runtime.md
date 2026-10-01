# Batch 35 Capability-Scoped Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator process serve the state plane when GitHub publication or intent interpretation is entirely unconfigured, and reject the missing capability before any checkpoint mutation.

**Architecture:** `RuntimeCapabilities` is explicit composition state with two fields, `intent_interpretation` and `source_control_publishing`. Lifespan opens SQLite after the operator secret and classifies those groups. Submit checks interpretation only after the existing `request_exists` read. Approve checks publication only when `decide_approval()` would resume an `approve`. `UnavailableSourceControl` exists so the graph can compile; the approve route must not call it. There is no unconfigured interpreter.

**Tech Stack:** Python 3.12, FastAPI, pytest, ruff. React tests only if a client mapping test is added. No new UI production code.

**Design:** `docs/superpowers/specs/2026-09-30-batch35-design.md`

## Global Constraints

- One process, one `state.db`. Do not add a second service or database.
- Startup still requires `IAC_AGENT_OPERATOR_SECRET`. Missing, empty, and whitespace-only values still raise `MissingConfigurationError` with the existing message, and the value is not in the message.
- Optional capabilities are only `intent_interpretation` and `source_control_publishing`. No plugin registry, service locator, or dependency-injection framework.
- Presence is `configured` or `absent`. Partial or invalid configuration raises `MissingConfigurationError` during startup and does not become `absent`.
- A variable is omitted when it is missing, empty, or whitespace-only. It is supplied when `strip()` is non-empty.
- GitHub presence group, exactly these existing names: `GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`, `GITHUB_COMMIT_AUTHOR_EMAIL`, `GITHUB_TOKEN`.
- `GITHUB_BASE_BRANCH=main`, or an omitted/blank branch, does not by itself make that group partial. Any other supplied branch with the group omitted is partial. A blank `GITHUB_BASE_BRANCH` beside a complete group is partial and must not silently become `main`.
- Interpreter presence group, exactly these existing names: `IAC_AGENT_LLM_PROVIDER`, `IAC_AGENT_LLM_MODEL`, `OPENAI_API_KEY`. Unknown provider with the other two supplied is invalid, not absent. The provider string may appear in the error. The API key must not.
- `IAC_AGENT_OBSERVABILITY=langfuse` with missing keys still fails startup. Default remains off. Do not put observability on `RuntimeCapabilities`.
- HTTP 503 body is exactly `{"error":"capability_unavailable","message":"..."}` with no `request_id`.
- Intent-absent message: `Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY.`
- Publication-absent message: `Source-control publishing is not configured. Set GITHUB_OWNER, GITHUB_REPOSITORY, GITHUB_COMMIT_AUTHOR_NAME, GITHUB_COMMIT_AUTHOR_EMAIL, and GITHUB_TOKEN.`
- Messages must not contain secret values, `Authorization` header values, checkpoint internals, or workspace paths.
- Authentication stays the first line of every `/api/v1/requests` handler.
- Submit order: authentication, body and id validation, existing `application.read` for `request_exists`, then the interpreter capability check, then `intent_service.submit`.
- Approve order: authentication, id and body validation, `application.read`, not-found, `decide_approval`. `conflict` and `return_current` return as they do today. The publication check runs only when the action is `resume` and the decision is `approve`, and it returns 503 before `application.resume`. `reject` resumes without that check.
- `/health` stays `{"status":"ok"}` and anonymous. `/ready` means the holder exists after the state plane opened. It does not probe GitHub or OpenAI and does not read capabilities.
- No checkpoint or `request_index` schema change. No `approved_by`. No successful DTO field. No workflow status for this error.
- Do not change `open_application`'s parameter list. `tests/unit/app/test_intent_application.py::test_open_application_signature_unchanged` locks `["config", "github_token", "github_transport"]`.
- Do not import `openai` at module scope in `src/iac_agent/app/composition.py`.
- Compose stays `127.0.0.1:8000:8000`. No TLS, ingress, remote bind, or public deployment.
- No Terraform apply or destroy. No live GitHub or OpenAI calls in deterministic tests.
- Browser secret stays in React memory. Do not add capability badges.
- Create commits with `git commit-tree` and `git reset --soft`, author and committer `IngMatrix-PGB <167713460+IngMatrix-PGB@users.noreply.github.com>`. Do not amend. The message must not contain `Co-Authored-By`, `Generated-By`, `Made with Cursor`, `Claude`, or `Anthropic`. Run `scripts/check_commit_attribution.py` on the message file before `commit-tree`.
- Do not modify the approved design document unless a task discovers a concrete repository contradiction. Record the contradiction in the commit message and stop for review rather than silently widening the design.

## File map

- Create `src/iac_agent/app/capabilities.py`: presence enum, `RuntimeCapabilities`, classifiers, and the two 503 messages.
- Create `src/iac_agent/git/unavailable.py`: `UnavailableSourceControl`.
- Create `tests/unit/app/test_capabilities.py`.
- Create `tests/unit/git/test_unavailable_source_control.py`.
- Create `tests/unit/api/test_capability_routes.py`.
- Modify `src/iac_agent/app/composition.py`: `IntentApplication.capabilities`, `intent_service` optional, new `open_operator_runtime`. `open_application` signature stays. `open_intent_application` still requires a token and an interpreter and sets both capabilities to `configured`.
- Modify `src/iac_agent/api/app.py`: lifespan loads the operator secret, then `open_operator_runtime()`.
- Modify `src/iac_agent/api/routes.py`: submit and approve gates.
- Modify injected `IntentApplication(...)` call sites so the new required field is set: `tests/integration/test_api_fresh_process.py`, `tests/unit/cli/test_failures.py`, `tests/unit/cli/test_resume.py`, `tests/unit/cli/test_propose.py`, `tests/integration/test_cli_e2e.py`, `tests/docker/harness.py`.
- Modify injected route holders that POST submit or approval so they expose `capabilities` with both values `configured`: `tests/unit/api/test_routes.py`, `tests/unit/api/test_operator_auth.py`, and `tests/unit/api/test_ui_static.py` if that holder posts those routes. List and detail holders do not need it.
- Modify `tests/unit/api/test_app.py`: replace `test_lifespan_still_requires_github_after_the_operator_secret` with the state-plane startup cases.
- Modify `tests/integration/test_api_fresh_process.py`: add the process-B proof.
- Modify `docs/api.md`, `docs/roadmap.md`, `tests/unit/docs/test_operator_ui_docs.py`.
- Modify `.env.example` with comments only. Do not change `IAC_AGENT_OPERATOR_SECRET=` or add a `VITE_` name.
- Modify `ui/src/api/client.test.ts` with one mapping row. Do not change `ui/src/api/client.ts` if that row passes immediately.
- Do not modify `request_index.py`, `schemas.py` success models, `domain/approval.py`, `compose.yaml` ports, `Dockerfile`, `ui/src/api/polling.ts`, or graph topology.

## Gate split

Gate A is pure classification and the source-control backstop. It does not boot HTTP. Gate B opens the state plane and changes lifespan. Gate C is the mutation guard on the two routes. Gate D is the cross-process proof, docs, and the client mapping test. The split follows the dependency order: routes cannot check a type that does not exist, and the fresh-process proof is meaningless until both the lifespan and the route guard exist.

---

## Gate A — classification and the source-control backstop

### Task 1: Capability classification

**Files:**
- Create: `src/iac_agent/app/capabilities.py`
- Test: `tests/unit/app/test_capabilities.py`

**Interfaces:**
- Produces: `CapabilityPresence`, `RuntimeCapabilities`, `classify_source_control_publishing(env) -> CapabilityPresence`, `classify_intent_interpretation(env) -> CapabilityPresence`, `classify_runtime_capabilities(env) -> RuntimeCapabilities`, `INTENT_ABSENT_MESSAGE`, `SOURCE_CONTROL_ABSENT_MESSAGE`
- Consumes: `MissingConfigurationError` and `IntentInterpreterProvider` from `iac_agent.app.config`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/app/test_capabilities.py`:

```python
import pytest

from iac_agent.app.capabilities import (
    INTENT_ABSENT_MESSAGE,
    SOURCE_CONTROL_ABSENT_MESSAGE,
    CapabilityPresence,
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


def test_empty_groups_are_absent_including_default_base_branch():
    env = {"GITHUB_BASE_BRANCH": "main"}
    assert classify_source_control_publishing(env) is CapabilityPresence.ABSENT
    assert classify_intent_interpretation({}) is CapabilityPresence.ABSENT
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
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/app/test_capabilities.py -q`

Expected: FAIL on import because `iac_agent.app.capabilities` does not exist.

- [ ] **Step 3: Minimum implementation**

Create `src/iac_agent/app/capabilities.py` with this module. A value is omitted when it is missing or `strip()` is empty. All five GitHub members omitted, with `GITHUB_BASE_BRANCH` omitted, blank, or `main`, returns `ABSENT`. All five supplied returns `CONFIGURED`, except a present blank `GITHUB_BASE_BRANCH`, which raises. A mixture, or a non-`main` branch while any member is omitted, raises `MissingConfigurationError` whose text is `GitHub publication configuration is partial — omitted: ` plus the omitted names, and appends `GITHUB_BASE_BRANCH` when that non-default branch is what made the group partial. All three interpreter variables omitted returns `ABSENT`. A mixture raises `Intent interpretation configuration is partial — omitted: ` plus the omitted names. When none are omitted, construct `IntentInterpreterProvider` from the stripped provider and reuse the existing unsupported-provider `MissingConfigurationError` text from `load_intent_interpreter_config_from_env`. `classify_runtime_capabilities` calls both classifiers and returns `RuntimeCapabilities`.

```python
class CapabilityPresence(StrEnum):
    CONFIGURED = "configured"
    ABSENT = "absent"


@dataclass(frozen=True)
class RuntimeCapabilities:
    intent_interpretation: CapabilityPresence
    source_control_publishing: CapabilityPresence
```

Do not add fields. Do not read `os.environ` inside the classifiers; the caller passes the mapping.

- [ ] **Step 4: GREEN**

Run the same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/capabilities.py tests/unit/app/test_capabilities.py
# commit-tree, no trailers
# message: feat: classify optional GitHub and interpreter capabilities
```

### Task 2: Unavailable source-control backstop

**Files:**
- Create: `src/iac_agent/git/unavailable.py`
- Test: `tests/unit/git/test_unavailable_source_control.py`

**Interfaces:**
- Produces: `UnavailableSourceControl.publish_change(...) -> NoReturn`, raises `SourceControlError`
- Consumes: `SourceControlError` from `iac_agent.git.port`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from iac_agent.git.port import SourceControlError
from iac_agent.git.unavailable import UnavailableSourceControl


def test_publish_change_refuses_without_a_credential():
    port = UnavailableSourceControl()
    with pytest.raises(SourceControlError) as exc:
        port.publish_change(
            request_id="req-1",
            base_branch="main",
            branch_name="iac-agent/req-1",
            files={"main.tf": 'resource "aws_sqs_queue" "this" {}'},
            commit_message="feat",
            pr_title="title",
            pr_body="body",
        )
    text = str(exc.value)
    assert text == "Source-control publishing is not configured."
    assert "aws_sqs_queue" not in text
    assert not hasattr(port, "_token")
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/git/test_unavailable_source_control.py -q`

Expected: FAIL on import.

- [ ] **Step 3: Minimum implementation**

`UnavailableSourceControl.publish_change` raises `SourceControlError("Source-control publishing is not configured.")`. It stores no token and does not read the environment. It ignores the arguments.

- [ ] **Step 4: GREEN**

Run the same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/git/unavailable.py tests/unit/git/test_unavailable_source_control.py
# message: feat: refuse publication from the unconfigured source-control port
```

---

## Gate B — state plane and lifespan

### Task 3: Open the operator runtime without optional credentials

**Files:**
- Modify: `src/iac_agent/app/composition.py`
- Modify: `src/iac_agent/api/app.py`
- Modify: `tests/unit/api/test_app.py`
- Modify: every `IntentApplication(...)` constructor listed in the file map
- Test: `tests/unit/api/test_app.py`

**Interfaces:**
- Consumes: `classify_runtime_capabilities`, `CapabilityPresence`, `UnavailableSourceControl`, existing `open_sqlite_checkpointer`, `open_request_index`, `build_sqs_workflow`, `create_intent_interpreter`, `GitHubSourceControl`, `build_observability`
- Produces: `open_operator_runtime(env: Mapping[str, str] | None = None) -> Iterator[IntentApplication]`
- `IntentApplication` fields: `config`, `intent_service: IntentResolutionService | None`, `application`, `capabilities: RuntimeCapabilities`

`open_application`'s signature stays. CLI `main()` still loads GitHub and OpenAI before `open_intent_application` and still exits on `MissingConfigurationError`. This task does not make the CLI start without those variables.

- [ ] **Step 1: Write the failing lifespan tests**

In `tests/unit/api/test_app.py`, keep the two operator-secret startup tests. Replace `test_lifespan_still_requires_github_after_the_operator_secret` with tests that monkeypatch a clean environment. Helper:

```python
_CAPABILITY_NAMES = (
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_COMMIT_AUTHOR_NAME",
    "GITHUB_COMMIT_AUTHOR_EMAIL",
    "GITHUB_TOKEN",
    "GITHUB_BASE_BRANCH",
    "IAC_AGENT_LLM_PROVIDER",
    "IAC_AGENT_LLM_MODEL",
    "OPENAI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def _isolated_env(monkeypatch, **extra: str) -> None:
    for name in _CAPABILITY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IAC_AGENT_OPERATOR_SECRET", "probe-secret-must-not-leak")
    monkeypatch.setenv("IAC_AGENT_OBSERVABILITY", "off")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)
```

Cases:

- Operator secret plus `GITHUB_BASE_BRANCH=main` and no other capability variables: `TestClient(create_app())` starts. Anonymous `GET /health` is 200 `{"status":"ok"}`. Anonymous `GET /ready` is 200 `{"status":"ready"}`. Neither body contains `probe-secret-must-not-leak`, `GITHUB_TOKEN`, or `OPENAI_API_KEY`. `app.state.holder.capabilities.source_control_publishing` is `ABSENT` and `intent_interpretation` is `ABSENT`. `app.state.holder.intent_service` is `None`.
- Same environment plus the three interpreter variables (`openai`, `gpt-test`, `test-openai-key-not-used`): startup succeeds, intent is `CONFIGURED`, publication is `ABSENT`, and `intent_service` is not `None`.
- Same base environment plus the five GitHub variables and no interpreter variables: startup succeeds, publication is `CONFIGURED`, intent is `ABSENT`.
- Both groups set: startup succeeds and both presences are `CONFIGURED`.
- Only `GITHUB_OWNER=example-user`: `TestClient(create_app())` raises `MissingConfigurationError`, the text contains `GITHUB_TOKEN`, and it does not contain a token value.
- Only `IAC_AGENT_LLM_PROVIDER=openai`: startup raises `MissingConfigurationError` containing `IAC_AGENT_LLM_MODEL`.
- `IAC_AGENT_OBSERVABILITY=langfuse` with both capability groups omitted and the Langfuse keys deleted: startup still raises `MissingConfigurationError` or `ObservabilityConfigurationError` naming `LANGFUSE_PUBLIC_KEY`.
- With both capabilities absent and the bearer `Authorization: Bearer probe-secret-must-not-leak`, `GET /api/v1/requests` is 200 and `requests` is `[]`. `GET /api/v1/requests/req-missing` is 404 `request_not_found`. Neither response is 503.

Do not call `POST /api/v1/requests` in this task. These tests must not require a network.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/api/test_app.py -q`

Expected: the absent-capability startup test FAILs because lifespan still raises `MissingConfigurationError` for `GITHUB_OWNER`. The existing operator-secret tests still PASS. If they fail, stop; do not change their expected message.

- [ ] **Step 3: Minimum implementation**

Add `capabilities: RuntimeCapabilities` to `IntentApplication`. Change `intent_service` to `IntentResolutionService | None`. Update every direct constructor to pass `capabilities=RuntimeCapabilities(CapabilityPresence.CONFIGURED, CapabilityPresence.CONFIGURED)` and the existing service. `open_intent_application` sets that same configured value because its callers already passed a token and an interpreter.

Add `open_operator_runtime(env=None)`:

1. `env = os.environ if env is None else env`.
2. `capabilities = classify_runtime_capabilities(env)`. This raises before any socket or SQLite open when a group is partial.
3. Load workspace and state db the same way `load_application_config_from_env` does (`IAC_AGENT_WORKSPACE_ROOT` default `artifacts`, `IAC_AGENT_STATE_DB` default `<workspace>/state.db`).
4. If publication is `configured`, `config = load_application_config_from_env(env)` and `token = load_github_token_from_env(env)`, then build `GitHubSourceControl` exactly as `open_application` does, including optional transport left `None` on this path. If publication is `absent`, build `ApplicationConfig` with the state paths, empty strings for owner, repository, and commit identity, and `github_base_branch="main"`. Those empty strings must not be passed to `GitHubSourceControl`. The port is `UnavailableSourceControl()`. Pass `base_branch="main"` into `build_sqs_workflow` only as the required argument.
5. If interpretation is `configured`, `interpreter = create_intent_interpreter(load_intent_interpreter_config_from_env(env), api_key=load_openai_api_key_from_env(env))`. If `absent`, `interpreter` is `None`.
6. `config.state_db_path.parent.mkdir(parents=True, exist_ok=True)`.
7. Open the checkpointer and, inside it, `build_sqs_workflow` with `TerraformCompositionRenderer`, `TerraformRunner`, `CheckovAdapter`, the port chosen above, `workspace_root`, and `base_branch` from `config.github_base_branch`. Then `build_observability(load_observability_settings_from_env(env))` and `open_request_index`. Build `IacApplication`. Build `IntentResolutionService` only when `interpreter` is not `None`.
8. Yield `IntentApplication`.

`_lifespan`, when `holder is None`:

```python
app.state.operator_secret = load_operator_secret_from_env()
with open_operator_runtime() as holder:
    app.state.holder = holder
    yield
```

Delete the lifespan calls that always load GitHub and OpenAI before that `with`. Keep the early return when an injected holder is already set. Do not clear `operator_secret` on that path.

- [ ] **Step 4: GREEN**

Run: `.venv/bin/python -m pytest tests/unit/api/test_app.py tests/unit/app/test_intent_application.py tests/unit/app/test_request_index_composition.py -q`

Expected: PASS, including `test_open_application_signature_unchanged` and the module-level openai import test.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/composition.py src/iac_agent/api/app.py tests/unit/api/test_app.py \
  tests/integration/test_api_fresh_process.py tests/unit/cli/test_failures.py \
  tests/unit/cli/test_resume.py tests/unit/cli/test_propose.py \
  tests/integration/test_cli_e2e.py tests/docker/harness.py
# message: feat: open the state plane without GitHub or OpenAI configuration
```

---

## Gate C — mutation guards

### Task 4: Submit rejects a missing interpreter before mutation

**Files:**
- Modify: `src/iac_agent/api/routes.py`
- Modify: injected holders that POST `/api/v1/requests` (`tests/unit/api/test_routes.py`, `tests/unit/api/test_operator_auth.py`, `tests/unit/api/test_ui_static.py` as applicable)
- Test: `tests/unit/api/test_capability_routes.py`

**Interfaces:**
- Consumes: `INTENT_ABSENT_MESSAGE`, `CapabilityPresence`, `RuntimeCapabilities`

- [ ] **Step 1: Write the failing test**

Use a fake holder. `application.read` returns `None` for `req-new` and a non-None object for `req-old`. `intent_service.submit` raises `AssertionError("submit must not run")`. `capabilities` is `RuntimeCapabilities(CapabilityPresence.ABSENT, CapabilityPresence.ABSENT)`. `create_app(holder, operator_secret=SecretStr("test-operator-secret"))`.

```python
def test_new_request_without_an_interpreter_does_not_submit():
    # POST /api/v1/requests with Authorization Bearer test-operator-secret
    # body {"natural_language_request": "build a queue", "request_id": "req-new"}
    # status 503
    # body == {"error": "capability_unavailable", "message": INTENT_ABSENT_MESSAGE}
    # "request_id" not in body
    # submit was not called


def test_existing_request_still_conflicts_without_an_interpreter():
    # same header, request_id req-old
    # status 409
    # body["error"] == "request_exists"
    # submit was not called


def test_unauthenticated_submit_is_401_before_the_capability_check():
    # no Authorization header, request_id req-new
    # status 401
    # body == {"error": "unauthenticated", "message": "Authentication is required."}
    # read was not called
```

`req-old` only needs `read` to return a non-None sentinel. The 409 branch returns before `project_view`.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/api/test_capability_routes.py -q -k "interpreter or unauthenticated_submit"`

Expected: the new-request test FAILs with `AssertionError: submit must not run` or a 500, because the route still calls `intent_service.submit`. The 401 test may already PASS because authentication is already first. If it passes immediately, keep it and do not change the 401 body. The 409 test may already PASS because the existence read is already before submit. If it passes immediately, keep it. Only the 503 test is required to be RED.

- [ ] **Step 3: Minimum implementation**

In `create_request`, after the `request_exists` return and before `intent_service.submit`:

```python
capabilities = getattr(holder, "capabilities", None)
if (
    not isinstance(capabilities, RuntimeCapabilities)
    or capabilities.intent_interpretation is CapabilityPresence.ABSENT
):
    return _error("capability_unavailable", INTENT_ABSENT_MESSAGE, 503)
```

Do not pass `request_id` into `_error`. On every existing injected holder that this route posts through, set `capabilities` to both `CONFIGURED` before this check ships, in this same step, or those tests will 503. Do not change `intent_service.submit` itself.

- [ ] **Step 4: GREEN**

Run: `.venv/bin/python -m pytest tests/unit/api/test_capability_routes.py tests/unit/api/test_routes.py tests/unit/api/test_operator_auth.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/api/routes.py tests/unit/api/test_capability_routes.py \
  tests/unit/api/test_routes.py tests/unit/api/test_operator_auth.py tests/unit/api/test_ui_static.py
# message: feat: reject submit when intent interpretation is absent
```

### Task 5: Approve rejects a missing publisher before resume

**Files:**
- Modify: `src/iac_agent/api/routes.py` (`submit_approval` only)
- Test: `tests/unit/api/test_capability_routes.py`

**Interfaces:**
- Consumes: `decide_approval`, `SOURCE_CONTROL_ABSENT_MESSAGE`, `ApprovalDecision`, `WorkflowStatus`, `WorkflowView`

- [ ] **Step 1: Write the failing tests**

Fake `application.read` returns a `WorkflowView` by id. `application.resume` records the decision and, for `reject`, returns a view with `workflow_status=REJECTED` and `approval_decision=REJECT`. For `approve`, `resume` raises `AssertionError("resume must not run")`. A `publish_change` spy on the holder raises `AssertionError("publish_change must not run")` if called. Capabilities are both `ABSENT` unless a test sets publication to `CONFIGURED`.

Views:

- `req-wait`: `AWAITING_APPROVAL`, `approval_decision=None`, other optional fields `None`
- `req-missing`: `read` returns `None`
- `req-published`: `PR_CREATED`, `approval_decision=APPROVE`, `pull_request=PullRequestResult(number=1, url="https://example.invalid/pull/1", branch="iac-agent/req-published", base_branch="main")`
- `req-rejected`: `REJECTED`, `approval_decision=REJECT`

Assertions:

- `POST .../req-wait/approval` `{"decision":"approve"}` with bearer: 503 and `SOURCE_CONTROL_ABSENT_MESSAGE`. `resume` was not called. `publish_change` was not called. A following `GET /api/v1/requests/req-wait` is 200 and `outcome` is `awaiting_approval`.
- `POST .../req-wait/approval` `{"decision":"reject"}`: 200 and `outcome` is `rejected`. `resume` was called with `ApprovalDecision.REJECT`.
- `POST .../req-missing/approval` `{"decision":"approve"}`: 404 `request_not_found`. `resume` was not called.
- `POST .../req-published/approval` `{"decision":"approve"}`: 200 `pr_created`. `resume` was not called. This is `return_current`.
- `POST .../req-rejected/approval` `{"decision":"approve"}`: 409 `approval_conflict`. `resume` was not called.
- No `Authorization` header on `req-wait` approve: 401, and `read` was not called.
- When capabilities are both `CONFIGURED`, approve on `req-wait` calls `resume` once. The fake `resume` may raise `AssertionError` only in the absent test; in this test it returns a `PR_CREATED` view. Status 200, `outcome` `pr_created`.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/api/test_capability_routes.py -q -k approval`

Expected: the absent-approve test FAILs because `resume` raises `AssertionError: resume must not run`. The 404, 409, repeated-approve, and 401 tests may already PASS. Keep them if they do. Do not weaken `decide_approval`.

- [ ] **Step 3: Minimum implementation**

In `submit_approval`, leave the conflict and `return_current` branches untouched. Immediately after them, before `application.resume`:

```python
if decision is ApprovalDecision.APPROVE:
    capabilities = getattr(request.app.state.holder, "capabilities", None)
    if (
        not isinstance(capabilities, RuntimeCapabilities)
        or capabilities.source_control_publishing is CapabilityPresence.ABSENT
    ):
        return _error(
            "capability_unavailable",
            SOURCE_CONTROL_ABSENT_MESSAGE,
            503,
        )
```

`reject` falls through to the existing `resume` call. Do not call `publish_change` from the route.

- [ ] **Step 4: GREEN**

Run: `.venv/bin/python -m pytest tests/unit/api/test_capability_routes.py tests/unit/api/test_routes.py tests/integration/test_api_fresh_process.py -q`

Expected: PASS. The existing fresh-process approve test stays green because `_holder` sets both capabilities to `configured`.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/api/routes.py tests/unit/api/test_capability_routes.py
# message: feat: reject approve when source-control publishing is absent
```

---

## Gate D — fresh process, docs, and regression

### Task 6: Process B reads and rejects a checkpoint created by process A

**Files:**
- Modify: `tests/integration/test_api_fresh_process.py`
- Test: `test_second_process_serves_durable_state_without_github_or_openai` in that file

**Interfaces:**
- Consumes: `create_app`, `open_operator_runtime` via lifespan, the existing `_holder` fakes, `_checkpoint_threads`, `_request_index_rows`

This is the architectural proof. Process A uses the injected fake interpreter and fake source control, with both capabilities `configured`, so it does not call OpenAI or GitHub. Process B uses `create_app()` with no holder, so it runs `_lifespan` and `open_operator_runtime` against the same `state.db`.

- [ ] **Step 1: Write the failing test**

Use `monkeypatch` and `_isolated_env` from Task 3, copied locally or imported only if that helper is moved to a test module. Do not import a private helper from `tests/unit` if that creates a cross-package dependency; duplicate the ten-line helper in this file instead.

Process A, inside `open_sqlite_checkpointer` and `open_request_index` on `tmp_path / "state.db"`:

- Build `_holder` with `FakeIntentInterpreter`, `FakeSourceControl`, and both capabilities `configured`.
- `TestClient(create_app(holder_a, operator_secret=SecretStr("test-operator-secret")))`.
- POST two requests, `req-reject` and `req-approve`, with the worker prompt and a supplied `request_id`. Both return 201 and `outcome` `awaiting_approval`.
- `source_a.calls` is empty.
- Exit the `with` blocks so process A's connections close.

Process B:

- `monkeypatch.setenv("IAC_AGENT_STATE_DB", str(db_path))` and `IAC_AGENT_WORKSPACE_ROOT` to `str(tmp_path)`.
- Isolated env: operator secret `test-operator-secret`, `IAC_AGENT_OBSERVABILITY=off`, `GITHUB_BASE_BRANCH=main`, capability group variables deleted.
- `TestClient(create_app())` with no holder.
- `GET /health` and `GET /ready` without `Authorization` are 200.
- With `Authorization: Bearer test-operator-secret`:
  - `GET /api/v1/requests` contains both ids with `workflow_status` `awaiting_approval`.
  - `GET /api/v1/requests/req-reject` is `awaiting_approval`.
  - `POST /api/v1/requests/req-reject/approval` `{"decision":"reject"}` is 200 and `outcome` is `rejected`.
  - `POST /api/v1/requests/req-approve/approval` `{"decision":"approve"}` is 503 `capability_unavailable` and `SOURCE_CONTROL_ABSENT_MESSAGE`.
  - `GET /api/v1/requests/req-approve` is still `awaiting_approval`.
- `pragma table_info(request_index)` is still `["request_id", "created_at"]`.
- The response text for the 503 and the list does not contain `test-operator-secret`, `test-github-token`, or `test-openai-key`.
- Assert `UnavailableSourceControl.publish_change` was not used by spying: wrap the class method only if the test can do it without a live GitHub client. The 503 plus unchanged GET is the route proof. A direct call count belongs on the unit test from Task 2; do not require a network library here.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/integration/test_api_fresh_process.py::test_second_process_serves_durable_state_without_github_or_openai -q`

Expected: FAIL before Task 3 and Task 5 exist, because process B dies on missing `GITHUB_OWNER` or approve resumes. After those tasks, this test should PASS on the first run. If it PASSes immediately once Tasks 3 and 5 are in the tree, record that and do not change production code in this task. If it FAILs, the failure is a bug in those tasks; fix the implementation, do not weaken the assertions.

- [ ] **Step 3: Minimum implementation**

No production change if the test passes. If process B re-enters Terraform nodes on reject, stop and report that LangGraph resume re-executes more than `approval_gate`. Do not add a fake runner to the production lifespan to hide that.

- [ ] **Step 4: GREEN**

Run the same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_api_fresh_process.py
# message: test: serve a restarted checkpoint without GitHub or OpenAI
```

Commit only if this task added or changed the test. Do not create an empty commit.

### Task 7: Document the state plane and the 503

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/roadmap.md`
- Modify: `.env.example` comments only
- Modify: `tests/unit/docs/test_operator_ui_docs.py`
- Modify: `ui/src/api/client.test.ts`
- Do not modify: `ui/src/api/client.ts` unless the new mapping test fails

- [ ] **Step 1: Write the failing doc assertions**

Extend `test_api_doc_describes_the_operator_ui` to require these sentences, or equivalent exact clauses if an existing sentence already says the same thing and the new text would duplicate it. Prefer adding one short paragraph rather than rewriting the Batch 34 authentication paragraph:

- `capability_unavailable`
- `Intent interpretation is not configured.`
- `Source-control publishing is not configured.`
- `/ready` means the state plane is open, not that GitHub or OpenAI is configured or reachable.
- List and detail do not require GitHub or OpenAI.
- Reject does not require GitHub.
- Approve requires the GitHub publication group.
- Submit of a new request requires the interpreter group.
- A partial group fails startup.
- `GITHUB_BASE_BRANCH=main` alone does not configure publication.
- Public deployment remains unsupported. Keep the existing sentence `The operator UI does not make this API safe for public Internet exposure.`
- Keep the existing health sentence that probes do not prove AWS, OpenAI, GitHub, Langfuse, or Terraform Registry connectivity.

Extend `test_roadmap_marks_batch_31_complete_without_auth`:

- `Batch 35 — capability-scoped runtime (complete)` is present.
- `lifespan or startup decoupling are not started` is absent.
- `GitHub and OpenAI configuration are still required before the process serves.` is absent.
- `not started` still contains RBAC, public deployment, TLS, and remote or public deployment.
- The design path `docs/superpowers/specs/2026-09-30-batch35-design.md` and this plan path are named.

In `ui/src/api/client.test.ts`, add one row to the existing `it.each` table:

```typescript
[503, "capability_unavailable", "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY."],
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q`

Expected: FAIL because the new clauses are absent.

Run from `ui/`: `npm test -- src/api/client.test.ts`

Expected: PASS immediately. `httpError` already copies `error` and `message`. Do not edit `client.ts`. If this Vitest command fails, stop; the client contract changed and the plan's assumption is wrong.

- [ ] **Step 3: Minimum implementation**

Update `docs/api.md` and `docs/roadmap.md` to satisfy the assertions. In `.env.example`, above the GitHub block, add a comment that empty GitHub and interpreter variables leave those capabilities absent, that `GITHUB_BASE_BRANCH=main` is the default and does not by itself configure publication, and that a mixture fails startup. Do not put sample secrets in the file. Do not change `IAC_AGENT_OPERATOR_SECRET=`.

Do not add a capabilities endpoint, a workflow status, or a UI badge.

- [ ] **Step 4: GREEN**

Run the pytest command again. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/api.md docs/roadmap.md .env.example tests/unit/docs/test_operator_ui_docs.py ui/src/api/client.test.ts
# message: docs: describe state-plane startup and capability_unavailable
```

### Task 8: Deterministic regression

**Files:** none, unless a previous task left a failure.

- [ ] **Step 1: Run the suite**

From `ui/`:

```bash
npm test
npm run build
npx playwright test
```

From the repository root:

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: pytest passes with the existing xfail count unchanged except for tests this plan added. Ruff is clean. `git diff --check` is clean. Playwright stays at the current passing count if no UI production file changed. Delete `ui/test-results` if Playwright creates it. Do not commit `ui/dist` or `ui/test-results`.

- [ ] **Step 2: Scope check**

`git diff --stat origin/main` includes no changes under `src/iac_agent/persistence/request_index.py`, `src/iac_agent/api/schemas.py` success models, `src/iac_agent/domain/approval.py`, `compose.yaml` port `127.0.0.1:8000:8000`, or `TerraformRunner` apply/destroy methods. `rg` across the branch diff finds no new `approved_by`, `localStorage.setItem`, or `VITE_` credential.

- [ ] **Step 3: Commit**

No commit if the tree is clean. If regression required a fix, commit that fix alone with a message that names the broken assertion. Do not amend earlier commits.

---

## Non-goals

This plan does not implement OAuth, OIDC, users, roles, RBAC, tenants, `approved_by`, durable identity, audit history, TLS, ingress, a reverse proxy, a remote bind, public deployment, a capability HTTP endpoint, capability persistence, checkpoint or index schema changes, workflow-status additions, successful DTO expansion, post-publish recovery, GitHub idempotency changes, or Terraform apply/destroy.

## Self-review

- Spec section 6 maps to Task 1 `RuntimeCapabilities`.
- Spec sections 8 and 9 map to Task 1 classifiers and Task 2 backstop.
- Spec sections 5, 14, and 15 map to Task 3 `open_operator_runtime` and `/health` `/ready` tests.
- Spec sections 10 and 11 map to Tasks 4 and 5, including the existence read before the interpreter check and `decide_approval` before the publication check.
- Spec section 12 maps to the reject test in Task 5 and the fresh-process reject in Task 6.
- Spec section 13 maps to Task 3 list/detail not reading capabilities, and Task 6 list/detail on process B.
- Spec section 16 maps to leaving interpreter and `source_control` error handling unchanged. No task edits `_error_update` or `publish_change` idempotency.
- Spec section 21's fresh-process proof is Task 6.
- `open_application` signature test is an explicit non-change in Task 3.
- UI production files are unchanged unless the client mapping test fails.
- Placeholder scan: no TBD, TODO, or "similar to Task N" implementation step. The env helper text says to duplicate it rather than invent a shared fixture.

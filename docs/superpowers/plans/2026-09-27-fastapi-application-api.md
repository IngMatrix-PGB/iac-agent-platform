# FastAPI application API implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing intent and workflow services over a loopback FastAPI adapter without a second orchestrator or a second request store.

**Architecture:** Routes call `IntentResolutionService.submit`, `IacApplication.read`, and `IacApplication.resume`. A pure projector builds public DTOs. `read` returns `None` for LangGraph's empty missing-thread snapshot. `get_state` stays the CLI read and may still project that snapshot as `pending`. Approval idempotency is decided from the durable `WorkflowView` before any `resume`.

**Tech Stack:** Python 3.12, existing Pydantic 2, FastAPI `TestClient`, the existing SQLite checkpointer. No Docker.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-27-fastapi-application-api-design.md`, section 11 closed.
- FastAPI is an inbound adapter. Routes must not import or call graph nodes, `TerraformRunner`, `CheckovAdapter`, the OpenAI adapter, the Langfuse SDK, `GitHubSourceControl`, `sqlite3`, or `open_sqlite_checkpointer`.
- Do not serialize `WorkflowState` or `WorkflowView` as the HTTP body.
- Do not add a request table, event store, or other persistence for clarification or unsupported outcomes.
- Public findings are only `policy_id`, `status`, and `severity`.
- Public workflow errors are `stage` and `error_type` only. The CLI keeps printing `WorkflowError.message`.
- Public pull-request field is `url` only.
- No Terraform source on any response. No Terraform route.
- Bind host constant is `127.0.0.1`. No auth, OAuth, OIDC, Cognito, JWT, API key, session, or RBAC.
- Same-decision success is only `pr_created` or `approved` plus stored `approve`, or `rejected` plus stored `reject`. `error` and `blocked` are conflicts, including `error` after a stored `approve`.
- Unknown valid id is HTTP 404. Never synthesize `pending`, `submitted`, or `awaiting_approval`.
- Do not edit `.github/workflows/ci.yml`, Terraform modules, `bootstrap/aws-oidc`, the observability package, or `docs/adr/2026-09-27-registry-catalog-deferred.md`. None of that ADR's reopen criteria are met.
- Tests stay in `pytest -m "not real_tool and not real_llm"`. No live AWS, OpenAI, GitHub, Langfuse, apply, or destroy.
- Commits must not contain `Co-Authored-By`, `Generated-By`, Cursor, Claude, or Anthropic trailers. `git commit` in this environment injects a trailer. Use `git commit-tree` and `git reset --soft`. Do not amend. Do not push.

## Gate structure

Gate A is tasks 1–6. Gate B is tasks 7–8.

Task 1 is before the routes. `IacApplication.get_state` currently does `snapshot.values.get("workflow_status", WorkflowStatus.PENDING)`, so an empty snapshot becomes `pending`. Putting the 404 rule only inside a route that called `get_state` would fail the regression. `read` is the application boundary the routes are allowed to call.

## File map

| File | Responsibility |
|---|---|
| `src/iac_agent/app/service.py` | `read` returns `None` when `created_at is None` |
| `src/iac_agent/api/schemas.py` | Public request and error DTOs |
| `src/iac_agent/api/project.py` | Projection only. No FastAPI import |
| `src/iac_agent/api/approval.py` | `decide_approval` |
| `src/iac_agent/api/routes.py` | Three `/api/v1` routes |
| `src/iac_agent/api/app.py` | `create_app`, health, readiness, `BIND_HOST` |
| `src/iac_agent/api/__init__.py` | Docstring only |
| `src/iac_agent/cli/ids.py` | Docstring: HTTP may call `generate_request_id` |
| `pyproject.toml` | `fastapi`, `httpx`, and `uvicorn` on the `dev` extra |
| `docs/api.md` | Operator contract and the v1 limits |
| `docs/roadmap.md` | FastAPI is no longer "not started" |
| `tests/unit/app/test_service.py` | Missing checkpoint versus CLI `get_state` |
| `tests/unit/api/test_project.py` | Allowlist and denylist |
| `tests/unit/api/test_approval.py` | Idempotency table |
| `tests/unit/api/test_app.py` | Health, readiness, loopback constant |
| `tests/unit/api/test_routes.py` | Status codes and the unknown-id 404 |
| `tests/unit/api/test_import_isolation.py` | Core modules do not import FastAPI |
| `tests/integration/test_api_fresh_process.py` | Close A, open B, GET, approve, fake PR URL |

---

### Task 1: Missing-checkpoint read

**Files:**
- Modify: `src/iac_agent/app/service.py`
- Test: `tests/unit/app/test_service.py`

**Interfaces:**
- Consumes: `workflow_config`, `_to_view`
- Produces: `IacApplication.read(self, request_id: str) -> WorkflowView | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/app/test_service.py`:

```python
def test_read_returns_none_for_an_empty_snapshot_and_get_state_stays_pending():
    class _Snapshot:
        def __init__(self, *, created_at, values):
            self.created_at = created_at
            self.values = values

    class _Graph:
        def __init__(self, snapshot):
            self._snapshot = snapshot

        def get_state(self, config):
            assert config["configurable"]["thread_id"] == "req-missing"
            return self._snapshot

    empty = IacApplication(_Graph(_Snapshot(created_at=None, values={})))
    assert empty.read("req-missing") is None
    assert empty.get_state("req-missing").workflow_status is WorkflowStatus.PENDING

    present = IacApplication(
        _Graph(
            _Snapshot(
                created_at="2026-09-27T00:00:00+00:00",
                values={"workflow_status": WorkflowStatus.AWAITING_APPROVAL},
            )
        )
    )
    found = present.read("req-missing")
    assert found is not None
    assert found.workflow_status is WorkflowStatus.AWAITING_APPROVAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/app/test_service.py::test_read_returns_none_for_an_empty_snapshot_and_get_state_stays_pending -q`

Expected: FAIL with `AttributeError: 'IacApplication' object has no attribute 'read'`

- [ ] **Step 3: Implement `read`**

In `src/iac_agent/app/service.py`, add this method before `get_state`. Leave `get_state` unchanged.

```python
def read(self, request_id: str) -> WorkflowView | None:
    """Return the checkpointed view, or None when no thread exists.

    LangGraph represents an unknown thread as a snapshot with
    `created_at is None` and empty values. This method does not turn
    that snapshot into `pending`. `get_state` remains the CLI read.
    """
    snapshot = self._graph.get_state(workflow_config(request_id))
    if snapshot.created_at is None:
        return None
    return _to_view(request_id, snapshot.values)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/app/test_service.py::test_read_returns_none_for_an_empty_snapshot_and_get_state_stays_pending -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/service.py tests/unit/app/test_service.py
TREE=$(git write-tree)
PARENT=$(git rev-parse HEAD)
NEW=$(git commit-tree "$TREE" -p "$PARENT" -m "$(cat <<'EOF'
feat(app): distinguish a missing workflow checkpoint

EOF
)")
git reset --soft "$NEW"
```

Confirm the message has no attribution trailer.

---

### Task 2: Public DTOs and projection

**Files:**
- Create: `src/iac_agent/api/__init__.py`
- Create: `src/iac_agent/api/schemas.py`
- Create: `src/iac_agent/api/project.py`
- Test: `tests/unit/api/test_project.py`

**Interfaces:**
- Consumes: `IntentSubmissionResult`, `WorkflowView`, `IacRequestSpec`
- Produces: `RequestResponse`, `project_submission`, `project_view`

`src/iac_agent/api/__init__.py` is a docstring only: `"""HTTP adapter. Routes are not imported here."""`

- [ ] **Step 1: Write the failing denylist test**

Create `tests/unit/api/test_project.py` with a submission whose view contains an address, a finding resource and message, an error message, a pull-request branch, and a prompt string that the projector must not receive. Assert the JSON keys and the rendered text.

```python
def test_projection_keeps_names_and_url_and_drops_denied_text():
    from iac_agent.api.project import project_submission

    body = project_submission(_submission())
    rendered = body.model_dump_json()
    assert body.resolution.name == "order-events"
    assert body.workflow.pull_request.url == "https://example.invalid/pull/7"
    assert body.workflow.findings[0].model_dump() == {
        "policy_id": "CKV_AWS_27",
        "status": "pass",
        "severity": "high",
    }
    assert body.workflow.error.error_type == "TerraformCommandError"
    assert "message" not in body.workflow.error.model_dump()
    for needle in (
        "module.queue.aws_sqs_queue.this",
        "arn:aws:s3:::order-events",
        "123456789012",
        "Checkov CKV_AWS_27 failed.",
        "benign failure",
        "iac-agent/req-001",
        "build a bucket named order-events",
        "# fake terraform",
    ):
        assert needle not in rendered
    assert "branch" not in body.workflow.pull_request.model_dump()
```

Build `_submission()` in the same file from `ResolvedArchitecture`, `SQSResourceSpec(name="order-events")`, a `PlanSummary` whose `resources_to_add` is `("module.queue.aws_sqs_queue.this",)`, a `SecurityFinding` with `resource="module.queue.aws_sqs_queue.this"` and `message="Checkov CKV_AWS_27 failed."`, a `WorkflowError` with `message="benign failure"`, and a `PullRequestResult` with `branch="iac-agent/req-001"`. The natural-language string is not an argument of `project_submission`.

Add `test_clarification_has_no_workflow` for `ClarificationRequired` and `test_unsupported_keeps_resolver_detail` for `UnsupportedArchitecture`. Both set `workflow` to `None` and `approval_available` to `False`.

Add `test_ecr_component_exposes_mutability_and_scan` using `EcrResourceSpec(name="orders")`. Expect one component, `role="repository"`, `name="orders"`, `image_tag_mutability="IMMUTABLE"`, `scan_on_push=True`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_project.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'iac_agent.api'`

- [ ] **Step 3: Implement the DTOs and projector**

`schemas.py` defines frozen Pydantic models: `FindingDTO` (`policy_id`, `status`, `severity` only), `PlanDTO`, `ComponentDTO`, `IntentDTO`, `ResolutionDTO`, `WorkflowErrorDTO` (`stage`, `error_type` only), `PullRequestDTO` (`url` only), `WorkflowDTO`, and `RequestResponse`. `RequestResponse` includes `terraform_apply: Literal["not_executed"] = "not_executed"`.

`project.py` copies fields by name. Plan counts come from `plan_summary.add_count`, `change_count`, `destroy_count`, and `destructive_change_detected`. Findings copy the three allowed fields from `view.security_gate.findings` in that object's existing order. `project_view` sets `intent` and `matched_pattern` to `None`. `project_submission` fills intent from `result.intent` using enum `.value` strings and sorted capabilities, and `matched_pattern` only for `ResolvedArchitecture`.

Architecture labels and component roles match `iac_agent.cli.present._architecture_label` and `_component_lines`. Standalone non-ECR specs set `components` to `[]` and `name` to `spec.name`. ECR uses `role="repository"` plus the mutability value and `scan_on_push`. Do not import FastAPI.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_project.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(api): project public request DTOs`

Use the `git commit-tree` sequence from task 1. Stage only the four files in this task.

---

### Task 3: Application factory, health, and the dev extra

**Files:**
- Modify: `pyproject.toml`
- Create: `src/iac_agent/api/app.py`
- Modify: `src/iac_agent/cli/ids.py` docstring only
- Test: `tests/unit/api/test_app.py`
- Test: `tests/unit/api/test_import_isolation.py`

**Interfaces:**
- Produces: `BIND_HOST = "127.0.0.1"`, `create_app(holder: IntentApplication | None = None) -> FastAPI`, `serve() -> None`

Dependency choice: add `fastapi>=0.115,<1`, `httpx>=0.27,<1`, and `uvicorn>=0.32,<1` to the `dev` extra only. Pydantic is already a base dependency. `TestClient` needs FastAPI and httpx. uvicorn is only the loopback server. Do not add these to `[project].dependencies`. Do not edit CI. No install was required to choose these floors; FastAPI 0.115 is the project floor that supports the already-pinned Pydantic 2.

- [ ] **Step 1: Write the failing tests**

`test_app.py` builds `create_app(holder=object())`, uses `TestClient`, and asserts `GET /health` is 200 `{"status": "ok"}` and `GET /ready` is 200 `{"status": "ready"}`. A second test sets `app.state.holder = None` and asserts `GET /ready` is 503 `{"status": "not_ready"}`. Assert neither body contains `state.db`, `artifacts`, or `GITHUB`. Assert `BIND_HOST == "127.0.0.1"`.

`test_import_isolation.py` parses AST and asserts `fastapi` is not imported by `src/iac_agent/app/service.py`, `intent/service.py`, `graph/workflow.py`, `cli/main.py`, or any file under `src/iac_agent/domain`. `api/app.py` may import it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_app.py tests/unit/api/test_import_isolation.py -q`

Expected: FAIL because `create_app` does not exist. Then install the extra once:

`.venv/bin/python -m pip install -e ".[dev]"`

Re-run. Expected still FAIL on the missing factory, not on a missing dependency.

- [ ] **Step 3: Implement the factory**

`create_app` stores `holder` on `app.state.holder`. Lifespan yields immediately when that holder is not `None`. When it is `None`, lifespan calls the same `load_application_config_from_env`, `load_github_token_from_env`, `load_intent_interpreter_config_from_env`, `load_openai_api_key_from_env`, `create_intent_interpreter`, and `open_intent_application` path the CLI uses, and stores the yielded `IntentApplication`. It does not construct Terraform or the graph itself.

`serve` calls `uvicorn.run(create_app, factory=True, host=BIND_HOST, port=8000)`.

Replace the `cli/ids.py` docstring so it says the CLI and the HTTP adapter may call `generate_request_id`, and `IacApplication` still requires an explicit id.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_app.py tests/unit/api/test_import_isolation.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(api): add a loopback FastAPI application factory`

---

### Task 4: POST /api/v1/requests

**Files:**
- Create: `src/iac_agent/api/routes.py`
- Modify: `src/iac_agent/api/app.py`
- Test: `tests/unit/api/test_routes.py`

**Interfaces:**
- Consumes: `project_submission`, `generate_request_id`, `validate_request_id`, `IacApplication.read`, `IntentResolutionService.submit`
- Produces: `register_routes(app: FastAPI) -> None`

- [ ] **Step 1: Write the failing route tests**

Use a fake holder. `intent_service.submit` returns scripted `IntentSubmissionResult` values. `application.read` returns `None` unless the test preloads a view. `application.get_state` raises `AssertionError`.

Assert:

- missing `natural_language_request` is 400 `invalid_request`
- `request_id` `foo/bar` sent as `foo%2Fbar` is 400 `invalid_request_id` and `submit` is not called
- a preloaded checkpoint for that id is 409 `request_exists` and `submit` is not called
- clarification and unsupported are 200, `workflow` is null, and a following `GET` is not this task
- a resolved awaiting-approval result is 201 with `Location: /api/v1/requests/{id}`
- omitted `request_id` uses an injected clock and entropy so the id is `req-20260927T191300Z-a1b2c3d4e5f6`
- `IntentProviderUnavailableError("secret downstream")` is 503 `intent_provider_unavailable`, and `secret downstream` is absent
- the prompt `build a bucket named order-events` is absent from a 201 body that still contains `order-events`

Register routes from `create_app` by calling `register_routes(app)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_routes.py -q`

Expected: FAIL with 404 from FastAPI because the route is not registered.

- [ ] **Step 3: Implement the route**

The handler generates or validates the id, calls `read`, and returns 409 when the view is not `None`. It then calls `submit`. `IntentInterpreterError` maps through the same type table as `iac_agent.cli.present._ERROR_CODES`, with the statuses in spec section 5.3. The message is the stable sentence, never `str(exc)`. A result with `workflow_view is None` is 200. Any other result is 201 plus the `Location` header. Unexpected exceptions become 500 `{"error": "internal_error", "message": "Internal error."}` with no exception text.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_routes.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(api): accept natural-language requests`

---

### Task 5: GET durable request, including the unknown-thread regression

**Files:**
- Modify: `src/iac_agent/api/routes.py`
- Modify: `tests/unit/api/test_routes.py`

**Interfaces:**
- Consumes: `IacApplication.read`, `project_view`
- Produces: `GET /api/v1/requests/{request_id}`

- [ ] **Step 1: Write the failing regression**

```python
def test_unknown_valid_request_id_is_404_and_not_a_synthetic_status(client, holder):
    response = client.get("/api/v1/requests/req-missing")
    assert response.status_code == 404
    body = response.json()
    assert body == {
        "error": "request_not_found",
        "message": "Request not found.",
    }
    rendered = response.text
    for forbidden in ("pending", "submitted", "awaiting_approval", "workflow_status"):
        assert forbidden not in rendered
    assert holder.application.get_state_calls == []
```

The fake `read` returns `None` and records no `get_state` call. A second test preloads an `AWAITING_APPROVAL` view and expects 200, `intent` null, `matched_pattern` null, and `approval_available` true. A third test repeats that GET and asserts `resume` was not called.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_routes.py::test_unknown_valid_request_id_is_404_and_not_a_synthetic_status -q`

Expected: FAIL with 404 from FastAPI's default route miss, or a body other than the documented error.

- [ ] **Step 3: Implement GET**

Validate the path id with `validate_request_id` before `read`. `ValueError` is 400 `invalid_request_id`. `None` is the 404 body above. A view is `project_view(view)` at 200. Do not call `get_state`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_routes.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(api): read durable requests without inventing state`

---

### Task 6: Approval route

**Files:**
- Create: `src/iac_agent/api/approval.py`
- Modify: `src/iac_agent/api/routes.py`
- Test: `tests/unit/api/test_approval.py`
- Modify: `tests/unit/api/test_routes.py`

**Interfaces:**
- Consumes: `WorkflowView`, `ApprovalDecision`
- Produces: `decide_approval(view: WorkflowView, decision: ApprovalDecision) -> Literal["resume", "return_current", "conflict"]`

- [ ] **Step 1: Write the failing decision table**

`test_approval.py` builds minimal `WorkflowView` values and asserts:

- `awaiting_approval` and either decision returns `resume`
- `pr_created` plus stored `approve`, decision `approve`, returns `return_current`
- `approved` plus stored `approve`, decision `approve`, returns `return_current`
- `rejected` plus stored `reject`, decision `reject`, returns `return_current`
- `rejected` plus decision `approve` returns `conflict`
- `pr_created` plus decision `reject` returns `conflict`
- `blocked` plus either decision returns `conflict`
- `error` plus stored `approve`, decision `approve`, returns `conflict`

Route tests assert the HTTP mapping: `resume` is called once for awaiting approval; a repeated approve against `pr_created` is 200 and does not call `resume`; approve while `blocked` or `error` is 409 `approval_conflict`, includes the current `request` object, and is not status 200; a missing id is 404; `{"decision": "yes"}` is 400 `invalid_approval`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_approval.py tests/unit/api/test_routes.py -q`

Expected: FAIL importing `decide_approval`

- [ ] **Step 3: Implement the decision and the route**

```python
def decide_approval(view: WorkflowView, decision: ApprovalDecision) -> Literal[
    "resume", "return_current", "conflict"
]:
    status = view.workflow_status
    stored = view.approval_decision
    if status is WorkflowStatus.AWAITING_APPROVAL:
        return "resume"
    if (
        decision is ApprovalDecision.APPROVE
        and stored is ApprovalDecision.APPROVE
        and status in (WorkflowStatus.PR_CREATED, WorkflowStatus.APPROVED)
    ):
        return "return_current"
    if (
        decision is ApprovalDecision.REJECT
        and stored is ApprovalDecision.REJECT
        and status is WorkflowStatus.REJECTED
    ):
        return "return_current"
    return "conflict"
```

The route parses `decision` with `parse_approval_decision`. `return_current` is 200 `project_view`. `conflict` is 409 with `error`, `message`, and `request`. `resume` calls `application.resume` once. If that call raises, `read` again and apply `decide_approval` to the new view. `return_current` becomes 200. `conflict` becomes 409. Anything else, including a still-missing view, is 500 `internal_error` without the exception text. Do not call `resume` again inside the handler.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_approval.py tests/unit/api/test_routes.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(api): resume approval idempotently`

---

### Task 7: Fresh-process HTTP proof

**Files:**
- Create: `tests/integration/test_api_fresh_process.py`

**Interfaces:**
- Consumes: `create_app`, `open_sqlite_checkpointer`, `build_iac_workflow`, `IntentApplication`

This test is unmarked. It uses fake Terraform, fake Checkov, and a fake source-control port. It is not `real_tool`.

- [ ] **Step 1: Write the test**

The test uses `FakeTerraformRunner`, `FakeCheckovAdapter`, and the interpreter shape from `tests/unit/cli/test_resume.py`. Replace that file's `FakeSourceControl.publish_change` return URL with `https://example.invalid/pull/7` and keep the call list. Do not import `iac_agent.git.github`.

1. Opens `tmp_path / "state.db"` with `open_sqlite_checkpointer`.
2. Builds `build_iac_workflow` with `AWSResourceRenderer`, a fake runner whose `show_json` returns one create, a non-blocking fake Checkov adapter, and a fake `publish_change` that records calls and returns `PullRequestResult(number=7, url="https://example.invalid/pull/7", branch="iac-agent/req-fresh", base_branch="main")`.
3. Wraps that graph in `IacApplication` and `IntentResolutionService` with a fake interpreter that returns a resolved SQS intent. The holder is an `IntentApplication`.
4. `POST /api/v1/requests` with `TestClient` and that holder. Assert 201 and `outcome == "awaiting_approval"`.
5. Closes the client, the context, and the checkpointer.
6. Opens a new checkpointer on the same file, builds a new graph, a new `IacApplication`, a new `IntentApplication`, and a new `TestClient`. The new interpreter must raise if called.
7. `GET /api/v1/requests/{request_id}` returns 200 `awaiting_approval`.
8. `POST /api/v1/requests/{request_id}/approval` with `{"decision": "approve"}` returns 200 `pr_created`.
9. `response.json()["workflow"]["pull_request"] == {"url": "https://example.invalid/pull/7"}`.
10. The fake `publish_change` was called once. It must not import or call `urllib`, `httpx`, or `GitHubSourceControl`.

- [ ] **Step 2: Run test to verify the current tree passes it**

Run: `.venv/bin/python -m pytest tests/integration/test_api_fresh_process.py -q`

Expected: PASS on the Gate A tree. If it fails, fix the adapter without adding a request table and without calling GitHub.

- [ ] **Step 3: Commit**

Message: `test(api): prove fresh-process HTTP resume`

---

### Task 8: Documentation and Gate B validation

**Files:**
- Create: `docs/api.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Write `docs/api.md`**

State the five routes, the DTO allowlist, and these limits in prose:

- clarification and unsupported responses are not in SQLite, and `GET` of those ids is 404
- findings are `policy_id`, `status`, and `severity`
- workflow errors expose `stage` and `error_type` only; the CLI still prints the message
- the pull-request field is `url`
- Terraform source is absent, and there is no source endpoint
- the server binds `127.0.0.1`, has no authentication, and is not production-ready for public exposure
- a later Docker batch must choose bind and network policy itself
- repeated approve or reject succeeds only when the checkpoint already proves that decision; `error` and `blocked` are conflicts
- unknown threads are 404, not `pending`
- Langfuse does not authorize requests and is not a readiness probe

- [ ] **Step 2: Update the roadmap sentence**

In `docs/roadmap.md`, replace the clause that says a FastAPI/HTTP adapter remains out of scope with a pointer to `docs/api.md` and the statement that the adapter is local and unauthenticated. Leave UI, Docker, and auth described as not started.

- [ ] **Step 3: Run the deterministic suite**

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: the suite passes, including `tests/unit/api` and `tests/integration/test_api_fresh_process.py`. Ruff passes. `git diff --check` passes.

- [ ] **Step 4: Commit**

Message: `docs: document the local FastAPI boundary`

Stage only `docs/api.md` and `docs/roadmap.md`.

## Spec coverage

| Closed decision | Task |
|---|---|
| Pre-workflow outcomes are not stored | 4 and 8 |
| Three finding fields | 2 |
| No `WorkflowError.message` on HTTP | 2; CLI untouched |
| Names and PR URL only | 2 |
| No Terraform body | 2 and 4; no route is added |
| Loopback, no auth | 3 and 8 |
| Idempotent same decision, conflict otherwise | 6 |
| Unknown thread is 404 | 1 and 5 |
| Fresh process GET then approve | 7 |

## Self-review notes

`get_state` synthesizing `pending` is existing behavior, verified in `src/iac_agent/app/service.py` `_to_view`. The plan does not change it. HTTP uses `read`.

`PullRequestResult.branch` remains on the domain object and the CLI. The HTTP DTO does not grow a `branch` field. Decision 4 closed the earlier draft that exposed `number`, `branch`, and `base_branch`.

A stored `approve` plus `workflow_status=error` is a 409. The earlier draft treated that as idempotent success. Decision 7 closed that.

No registry/catalog change is required. The ADR reopen criteria are unchanged by an HTTP adapter.

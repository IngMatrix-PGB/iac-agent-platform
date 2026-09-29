# Batch 33 Durable Request Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the local operator discover checkpointed request ids without making the index a second workflow authority.

**Architecture:** `request_index` is an application-owned table in the existing `state.db`. It stores `request_id` and server-generated `created_at` only. `IacApplication.submit` inserts a row after `graph.invoke` returns. `GET /api/v1/requests` reads the newest rows from that table and projects `workflow_status`, `approval_available`, `security_status`, and `name` through `IacApplication.read`. The LangGraph checkpoint stays the workflow authority. `SqliteSaver.list` is not the catalog.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite, React 19, TypeScript, Vitest, Playwright, pytest, ruff.

## Global Constraints

- No `terraform apply` and no `terraform destroy`.
- No new workflow status, LangGraph node, approval state, polling rule, Checkov change, or GitHub publication change.
- `RequestResponse` does not gain fields. `POST /api/v1/requests`, `GET /api/v1/requests/{request_id}`, and `POST /api/v1/requests/{request_id}/approval` keep their current bodies and status codes.
- The API stays unauthenticated. Compose stays `127.0.0.1:8000:8000`. This batch is not a public-exposure approval.
- No `localStorage`, `sessionStorage`, or `IndexedDB`.
- No new package, lockfile change, Dockerfile change, Compose change, or CI change.
- Do not call `SqliteSaver.list` to build the catalog.
- Do not backfill pre-existing checkpoints.
- Do not persist clarification, unsupported, or interpreter-failure results.
- Index insert failure does not roll back a checkpoint and does not change a successful 201 body.
- No attribution trailers (`Co-Authored-By`, `Generated-By`, `Made with Cursor`, `Claude`, `Anthropic`) on commits. If `git commit` injects one, create the commit with `git commit-tree` instead and do not amend.

---

## File map

- Create `src/iac_agent/persistence/request_index.py`. Owns the table, idempotent insert, and newest-first query. Uses its own SQLite connection to `state.db`, not the checkpointer connection.
- Modify `src/iac_agent/app/service.py`. `IacApplication.submit` records the id after a successful invoke. `list_requests` reads the index and drops rows whose checkpoint `read` returns `None`.
- Modify `src/iac_agent/app/composition.py`. `open_intent_application` opens the index and passes it into `IacApplication`. CLI and HTTP both use this function today.
- Modify `src/iac_agent/api/schemas.py`. Add `RequestListItem` and `RequestListResponse`.
- Modify `src/iac_agent/api/project.py`. Add `project_list_item`.
- Modify `src/iac_agent/api/routes.py`. Add `GET /api/v1/requests`.
- Modify `ui/src/api/types.ts` and `ui/src/api/client.ts`. Add a list type and `listRequests`. Do not send that body through `isRequestResponse`.
- Modify `ui/src/pages/compose-page.tsx` and `ui/src/styles.css`. Add Recent requests.
- Modify `tests/browser/serve_fake_ui.py`. `BrowserApplication.list_requests` returns an empty list so the existing browser tests can load `/`.
- Modify `tests/integration/test_api_fresh_process.py`. Process B lists the row written by process A.
- Modify `docs/api.md` and `docs/roadmap.md`.
- Create unit tests named in the tasks below.

Do not modify `src/iac_agent/graph/workflow.py`, `src/iac_agent/persistence/checkpoints.py` table layout, `Dockerfile`, `compose.yaml`, or `.github/workflows/ci.yml`.

## Public API contract

`GET /api/v1/requests`

Query `limit`:

- omitted: 20
- integer 1 through 50: that limit
- `0`, negative, greater than 50, or not an integer: HTTP 422 from FastAPI/Pydantic `Query(ge=1, le=50)`. Do not clamp. Do not map this to `invalid_request`.

No `cursor`. No `offset`. The body is only the newest `limit` index rows that still have a checkpoint. Older rows are not returned.

HTTP 200:

```json
{
  "requests": [
    {
      "request_id": "req-20260929T000000Z-abcdef012345",
      "created_at": "2026-09-29T00:00:00.000000Z",
      "workflow_status": "awaiting_approval",
      "approval_available": true,
      "security_status": "pass",
      "name": "orders"
    }
  ]
}
```

`created_at` comes from the index. The other dynamic fields come from `IacApplication.read`:

- `workflow_status`: `view.workflow_status.value` (always a string when `read` returns a view; `_to_view` defaults a missing status to `pending`, and `read` returns `None` instead of a view when `snapshot.created_at is None`)
- `approval_available`: true only when `view.workflow_status is WorkflowStatus.AWAITING_APPROVAL`
- `security_status`: `view.security_status`, JSON null when the checkpoint has no security gate
- `name`: `view.resource_name`, JSON null when the checkpoint has no resource spec

Empty catalog: `200` and `{"requests": []}`.

Stale index row: `read` returns `None`. Omit that id. Do not invent a status. Do not read past the newest `limit` rows to fill the gap. The array may be shorter than `limit`.

`GET /api/v1/requests/{request_id}` stays the one-id route. Register the collection route in `register_routes` before the parameterized route. A test must show `GET /api/v1/requests` is the list, not a request id lookup and not the UI `index.html`.

## Persistence schema

```sql
CREATE TABLE IF NOT EXISTS request_index (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
)
```

`created_at` is UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ` from `datetime.now(UTC)` inside `RequestIndex.record`, unless a test passes a clock callable. Six fractional digits. Not browser time, not a filesystem mtime, not a checkpoint field.

Insert:

```sql
INSERT OR IGNORE INTO request_index (request_id, created_at) VALUES (?, ?)
```

The first `created_at` wins. Validate `request_id` with `validate_request_id` before insert.

List:

```sql
SELECT request_id, created_at
FROM request_index
ORDER BY created_at DESC, request_id DESC
LIMIT ?
```

`open_request_index(db_path)` opens a second `sqlite3` connection (`check_same_thread=False`), sets `PRAGMA busy_timeout=5000`, creates the table, commits, yields `RequestIndex`, and closes the connection on exit. It does not call `SqliteSaver.list` and does not create LangGraph's `checkpoints` table. `open_application` already creates the parent directory and the database file. Call `open_request_index` inside `open_intent_application` while that context is open.

## Insert semantics

Insertion point, proven from current code:

- `IntentResolutionService.submit` calls `self._application.submit` only inside `case ResolvedArchitecture()`.
- Clarification, unsupported, and interpreter exceptions return or raise before that call.
- `IacApplication.submit` is the method that calls `self._graph.invoke(...)`. When invoke returns, LangGraph has checkpointed the thread (`SqliteSaver.cursor` commits on the way out).
- `resume` must not be treated as a new catalog entry. A duplicate `record` is `INSERT OR IGNORE`.

Call `request_index.record(request_id)` in `IacApplication.submit` after `invoke` and `_emit` have succeeded, immediately before `return view`.

## Failure semantics

```python
try:
    self._request_index.record(request_id)
except Exception as exc:
    logging.getLogger("iac_agent.persistence").warning(
        "request index insert failed",
        extra={"request_id": request_id, "error_type": type(exc).__name__},
    )
```

Follow `FailOpenObservability`: log `error_type`, not the exception text and not the checkpoint. No retry. No background repair. The view already built is what the HTTP 201 body uses. If `invoke` raises, do not record.

## Projection semantics

```text
newest index rows
    -> request ids
    -> IacApplication.read
    -> drop None
    -> project_list_item
```

The route does not read `snapshot.values` itself.

## UI behavior

Compose page section heading: `Recent requests`.

On mount, call `client.listRequests()` once. Do not poll.

- Loading copy: `Loading requests.`
- Empty copy: `No indexed requests. An older request can still be opened by its id.`
- Error: existing `ErrorBanner` with the client message.
- Each row is a link to `/requests/{request_id}` showing the id, the name when non-null, the raw `workflow_status`, and the raw `security_status` when non-null.
- Keep `Open a saved request` and `OpenRequest`.
- No search, filter, sort controls, or infinite scroll.

## Security negatives

A route test builds a checkpoint view that contains a finding `resource`, a finding `message`, `WorkflowError.message`, a plan resource address, Terraform source text, a workspace path, the word `checkpoints`, a GitHub owner, a GitHub repository, and a token-like string. The list JSON must not contain those strings. `policy_id` / `status` / `severity` are also absent because findings are not on the list row.

## Migration

No backfill. A checkpoint with no index row does not appear. `GET` by id still works. The UI empty/absence copy says an older id can still be opened.

## Durability proof

Extend `tests/integration/test_api_fresh_process.py`. It already closes process A's checkpointer and opens process B on the same file. Process A must write an index row. Process B, with a new index connection, `GET /api/v1/requests` and still `GET` the request.

Do not add a Docker test. `tests/docker/test_volume_resume.py` drives `tests/docker/harness.py`, which constructs `IacApplication(graph)` directly and is not `open_intent_application`. The index lives in the same `state.db` the volume already mounts. No image or compose change is required to prove that file survives replacement. The fresh-process test is the proof this batch adds.

`tests/browser/serve_fake_ui.py` must grow `BrowserApplication.list_requests` returning `[]`. The compose page will fetch the list on load. Without that method the existing Playwright tests 500.

## Test strategy

Deterministic pytest and Vitest. Playwright is the existing two tests plus the heading they will see on `/`. No `real_tool`, `real_llm`, or `docker` marker on new tests.

## Gate structure

- Gate A: persistence and submit/list behavior on `IacApplication`.
- Gate B: public schema, route, composition wiring, server negative test.
- Gate C: typed client, Recent requests, fake browser application.
- Gate D: fresh-process durability, docs, full regression.

This matches the repository boundaries. The prompt's likely Gate D Docker case is intentionally the existing fresh-process test instead.

## Validation commands

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

## Commit strategy

One commit per task, subjects below. No attribution trailers. Do not amend. Do not push during implementation unless a later human instruction says so.

## Stop conditions

Stop if the work needs a `RequestResponse` field, a workflow change, `SqliteSaver.list` as the catalog, a second database, backfill, auth, a package, Docker, Compose, or CI. Stop if invalid `limit` cannot be expressed as HTTP 422 without clamping.

---

### Task 1: Request index table

**Files:**
- Create: `src/iac_agent/persistence/request_index.py`
- Test: `tests/unit/persistence/test_request_index.py`

**Interfaces:**
- Consumes: `validate_request_id` from `iac_agent.domain.workflow`
- Produces: `open_request_index(db_path: Path) -> Iterator[RequestIndex]`, `RequestIndex.record(request_id: str) -> None`, `RequestIndex.newest(limit: int) -> tuple[tuple[str, str], ...]`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from iac_agent.persistence.request_index import open_request_index

_CLOCK = lambda: datetime(2026, 9, 29, 0, 0, tzinfo=UTC)


def test_record_is_idempotent_and_newest_orders_by_time_then_id(tmp_path):
    db = tmp_path / "state.db"
    db.touch()
    with open_request_index(db, clock=_CLOCK) as index:
        index.record("req-b")
        index.record("req-a")
        index.record("req-b")
        assert index.newest(1) == (("req-b", "2026-09-29T00:00:00.000000Z"),)
        assert index.newest(20) == (
            ("req-b", "2026-09-29T00:00:00.000000Z"),
            ("req-a", "2026-09-29T00:00:00.000000Z"),
        )
```

Equal timestamps sort `request_id` descending, so `req-b` precedes `req-a`. A second `record("req-b")` does not change `created_at` and does not add a row.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/persistence/test_request_index.py -q`

Expected: FAIL, `request_index` cannot be imported.

- [ ] **Step 3: Write minimal implementation**

`RequestIndex.record` validates the id, formats the clock with `"%Y-%m-%dT%H:%M:%S.%fZ"`, and runs `INSERT OR IGNORE`. `newest` runs the ordered `LIMIT` query. `open_request_index` creates the table on a dedicated connection and closes it. Default clock is `lambda: datetime.now(UTC)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/persistence/test_request_index.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/persistence/request_index.py tests/unit/persistence/test_request_index.py
git commit -m "$(cat <<'EOF'
feat: add the durable request index table

EOF
)"
```

### Task 2: Record after submit and skip a missing checkpoint

**Files:**
- Modify: `src/iac_agent/app/service.py`
- Test: `tests/unit/app/test_request_index_submit.py`

**Interfaces:**
- Consumes: `RequestIndex.record` and `RequestIndex.newest`
- Produces: `IacApplication.submit` best-effort record; `IacApplication.list_requests(*, limit: int) -> tuple[IndexedRequest, ...]`; `IndexedRequest(view: WorkflowView, created_at: str)`

- [ ] **Step 1: Write the failing test**

Use a graph whose `invoke` returns `{"request_id": "req-1", "workflow_status": WorkflowStatus.AWAITING_APPROVAL}` and whose `get_state` returns a snapshot with `created_at` set and those values. Pass a fake index with `record` and `newest`.

Assert:

- one successful `submit` calls `record` once with `req-1` and still returns `workflow_status == AWAITING_APPROVAL`
- when `invoke` raises `RuntimeError`, `record` is not called and the exception propagates
- when `record` raises `RuntimeError`, `submit` still returns the view
- `list_requests` omits an id whose snapshot `created_at is None` and keeps an id whose snapshot exists, in the index order, without inventing `pending` for the missing one

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/app/test_request_index_submit.py -q`

Expected: FAIL, `list_requests` or the index argument does not exist.

- [ ] **Step 3: Write minimal implementation**

Add optional `request_index=None` to `IacApplication.__init__`. Default is a null index whose `record` returns and whose `newest` returns `()`. Existing `IacApplication(graph)` call sites stay valid.

After `_emit` in `submit`, call `_record_index`. Do not wrap `invoke`. `list_requests` zips `newest(limit)` through `read` and drops `None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/app/test_request_index_submit.py tests/unit/app/test_service.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/service.py tests/unit/app/test_request_index_submit.py
git commit -m "$(cat <<'EOF'
feat: index a request after its checkpoint exists

EOF
)"
```

### Task 3: Public list schema

**Files:**
- Modify: `src/iac_agent/api/schemas.py`
- Modify: `src/iac_agent/api/project.py`
- Test: `tests/unit/api/test_request_list_projection.py`

**Interfaces:**
- Consumes: `WorkflowView`, `WorkflowStatus`
- Produces: `RequestListItem`, `RequestListResponse`, `project_list_item(view, *, created_at: str) -> RequestListItem`

- [ ] **Step 1: Write the failing test**

Build a `WorkflowView` for `req-1` at `AWAITING_APPROVAL` with `resource_name="orders"`, `security_status="pass"`, a `SecurityGateResult` whose finding has `resource="aws_sqs_queue.hidden"` and `message="HIDDEN_FINDING_MESSAGE"`, a `WorkflowError` whose `message` is `HIDDEN_WORKFLOW_ERROR_MESSAGE`, and a `PlanSummary` only if constructing one is required by the view. `project_list_item(...).model_dump()` equals:

```python
{
    "request_id": "req-1",
    "created_at": "2026-09-29T00:00:00.000000Z",
    "workflow_status": "awaiting_approval",
    "approval_available": True,
    "security_status": "pass",
    "name": "orders",
}
```

The dumped JSON does not contain `HIDDEN_FINDING_MESSAGE`, `aws_sqs_queue.hidden`, or `HIDDEN_WORKFLOW_ERROR_MESSAGE`. A second view with `security_status=None` and `resource_name=None` dumps those two keys as `None`. `approval_available` is false when status is `BLOCKED`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_request_list_projection.py -q`

Expected: FAIL, `project_list_item` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add the two frozen models. `project_list_item` copies only the six fields. Do not add fields to `RequestResponse`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_request_list_projection.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/api/schemas.py src/iac_agent/api/project.py tests/unit/api/test_request_list_projection.py
git commit -m "$(cat <<'EOF'
feat: project the public request list row

EOF
)"
```

### Task 4: List route

**Files:**
- Modify: `src/iac_agent/api/routes.py`
- Modify: `tests/unit/api/test_routes.py` only if `FakeApplication` must grow `list_requests` for the new tests in the new file. Prefer a new test module so existing route tests stay untouched.
- Test: `tests/unit/api/test_request_list_route.py`

**Interfaces:**
- Consumes: `project_list_item`, `IacApplication.list_requests`
- Produces: `GET /api/v1/requests`

- [ ] **Step 1: Write the failing test**

`FakeApplication.list_requests` records `limit` and returns one `IndexedRequest`. Holder matches `tests/unit/api/test_routes.py`.

Assert:

- `GET /api/v1/requests` calls `list_requests(limit=20)` and returns the six-field row
- `GET /api/v1/requests?limit=50` passes 50
- `GET /api/v1/requests?limit=0`, `?limit=-1`, `?limit=51`, and `?limit=nope` return 422 and do not call `list_requests`
- `GET /api/v1/requests/{id}` for a stored view is unchanged
- response text for a hostile view does not contain `arn:aws:sqs:us-east-1:123456789012:hidden`, `HIDDEN_FINDING_MESSAGE`, `aws_sqs_queue.hidden_address`, `HIDDEN_WORKFLOW_ERROR_MESSAGE`, `/var/lib/iac-agent/workspaces`, `checkpoints`, `example-owner`, `example-repo`, `ghp_hidden_token_value`, or `resource "aws_sqs_queue"`

Put the hostile strings on the view's finding, error message, and resource name only where the assertion says they must be absent. The public `name` in that test should be a safe value such as `orders`, not one of the forbidden strings.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_request_list_route.py -q`

Expected: FAIL with 404 for `GET /api/v1/requests`.

- [ ] **Step 3: Write minimal implementation**

```python
@app.get("/api/v1/requests")
def list_requests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
):
    entries = request.app.state.holder.application.list_requests(limit=limit)
    body = RequestListResponse(
        requests=[
            project_list_item(entry.view, created_at=entry.created_at) for entry in entries
        ]
    )
    return body
```

Register it before `GET /api/v1/requests/{request_id}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_request_list_route.py tests/unit/api/test_routes.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/api/routes.py tests/unit/api/test_request_list_route.py
git commit -m "$(cat <<'EOF'
feat: list the newest checkpointed requests

EOF
)"
```

### Task 5: Wire the index into composition

**Files:**
- Modify: `src/iac_agent/app/composition.py`
- Test: `tests/unit/app/test_request_index_composition.py`

**Interfaces:**
- Consumes: `open_request_index`, `IacApplication(..., request_index=index)`
- Produces: `open_intent_application` yields an application whose index writes to `config.state_db_path`

- [ ] **Step 1: Write the failing test**

Monkeypatch `open_application` to yield `Application(config=config, graph=object())` without constructing Terraform. Monkeypatch `build_observability` to return `FailOpenObservability(NoOpObservability())`. Call `open_intent_application` with a fake interpreter and `SecretStr("test")`. `record("req-wire")` on the yielded application index. Exit the context. Open `open_request_index` on the same path and assert `newest(20)` returns that id.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/app/test_request_index_composition.py -q`

Expected: FAIL because the yielded application still has the null index, so the reopened table has no row.

- [ ] **Step 3: Write minimal implementation**

Inside `open_intent_application`, under `open_application`:

```python
with open_request_index(application.config.state_db_path) as index:
    iac = IacApplication(
        application.graph,
        observability=observability,
        request_index=index,
    )
    ...
    yield IntentApplication(...)
```

The index connection closes when the intent application context closes. The checkpointer connection remains the one `open_application` already owns.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/app/test_request_index_composition.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/composition.py tests/unit/app/test_request_index_composition.py
git commit -m "$(cat <<'EOF'
feat: open the request index with the application

EOF
)"
```

### Task 6: Typed list client

**Files:**
- Modify: `ui/src/api/types.ts`
- Modify: `ui/src/api/client.ts`
- Test: `ui/src/api/client.test.ts`

**Interfaces:**
- Consumes: `GET /api/v1/requests?limit=`
- Produces: `ApiClient.listRequests(limit?: number) -> Promise<RequestListResult>`

`RequestListResult` is `{ kind: "success"; status: number; body: RequestListResponse }`, the existing HTTP error shape, or the existing network error. It is not `ClientResult`, because `ClientResult` success requires `RequestResponse`.

- [ ] **Step 1: Write the failing test**

A fetch mock for `GET /api/v1/requests?limit=20` returning the six-field JSON resolves `kind: "success"`. A response that is a `RequestResponse` without `requests` is `kind: "http"`. `listRequests` does not call `POST`.

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/api/client.test.ts`

Expected: FAIL, `listRequests` is not a function.

- [ ] **Step 3: Write minimal implementation**

Add the interfaces. `listRequests` fetches `/api/v1/requests` and appends `?limit=` only when the argument is present. Validate `requests` is an array of objects with the six keys. Do not change `submit`, `getRequest`, or `decide`.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/api/client.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/types.ts ui/src/api/client.ts ui/src/api/client.test.ts
git commit -m "$(cat <<'EOF'
feat: add the request list client

EOF
)"
```

### Task 7: Recent requests

**Files:**
- Modify: `ui/src/pages/compose-page.tsx`
- Modify: `ui/src/styles.css`
- Test: `ui/src/app.test.tsx` or `ui/src/pages/compose-page.test.tsx` if the compose page is not already mounted by `app.test.tsx`. `app.test.tsx` renders the compose route, so extend that file only if its client fake can grow `listRequests`. If the fake is a partial `ApiClient`, add the method there.

**Interfaces:**
- Consumes: `client.listRequests`
- Produces: heading `Recent requests`, links to `/requests/{id}`

- [ ] **Step 1: Write the failing test**

The client fake resolves one row `req-listed` / `orders` / `awaiting_approval` / `pass`. The compose page shows heading `Recent requests`, a link named with `req-listed`, the raw status `awaiting_approval`, and `pass`. Activating the link navigates to `/requests/req-listed`. A second case resolves `requests: []` and shows `No indexed requests. An older request can still be opened by its id.` The typed opener still works. The test reads `localStorage`/`sessionStorage` call counts as zero if the test harness can spy them; otherwise assert the page source under test does not reference those names by keeping the component free of them and asserting the empty copy instead.

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: FAIL, heading `Recent requests` is missing.

- [ ] **Step 3: Write minimal implementation**

Load the list in an effect. Render the section above the existing `Open a saved request` heading. Use a definition list or a row of text inside the link. Reuse `.panel` and existing tokens. No new dependency. Do not store the response.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/app.test.tsx src/pages/request-page.test.tsx`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/compose-page.tsx ui/src/styles.css ui/src/app.test.tsx
git commit -m "$(cat <<'EOF'
feat: show recent requests on the compose page

EOF
)"
```

If the new test lives in a new file, add that file instead of assuming `app.test.tsx`.

### Task 8: Keep the fake browser server compatible

**Files:**
- Modify: `tests/browser/serve_fake_ui.py`
- Modify: `ui/e2e/approve.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/requests` on the fake holder
- Produces: `BrowserApplication.list_requests` returns `()`

- [ ] **Step 1: Write the failing test**

In `approve.spec.ts`, after the page loads and before submit, expect heading `Recent requests` and text `No indexed requests. An older request can still be opened by its id.`

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npx playwright test e2e/approve.spec.ts`

Expected: FAIL until both the UI from Task 7 and this fake method exist. If Task 7 is already committed, the failure is a 500 from the missing method or a missing empty sentence. Do not weaken the existing approve assertions.

- [ ] **Step 3: Write minimal implementation**

```python
def list_requests(self, *, limit: int):
    del limit
    return ()
```

on `BrowserApplication`. Do not index the in-memory browser workflow. The existing approve path still navigates on 201.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npx playwright test`

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add tests/browser/serve_fake_ui.py ui/e2e/approve.spec.ts
git commit -m "$(cat <<'EOF'
test: keep the browser fake compatible with the request list

EOF
)"
```

### Task 9: Fresh-process durability

**Files:**
- Modify: `tests/integration/test_api_fresh_process.py`
- Modify: `_holder` in that file so process A and process B each receive a `RequestIndex` opened on `db_path`

**Interfaces:**
- Consumes: `open_request_index`, `IacApplication(..., request_index=index)`
- Produces: proof that process B lists the row and still reads the checkpoint

- [ ] **Step 1: Write the failing assertion**

After process A's 201, and inside process B's client, before approve:

```python
listed = client_b.get("/api/v1/requests")
assert listed.status_code == 200
body = listed.json()
assert body["requests"][0]["request_id"] == _REQUEST_ID
assert body["requests"][0]["workflow_status"] == "awaiting_approval"
assert "module.queue.aws_sqs_queue.this" not in listed.text
```

Open the index context around each holder, and close it when that holder's checkpointer context ends. Process B must construct a new `RequestIndex`, not reuse process A's object.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_api_fresh_process.py -q`

Expected: FAIL because `_holder` still builds `IacApplication` without an index, so the list is empty.

- [ ] **Step 3: Write minimal implementation**

Pass `request_index=index` into the `IacApplication` constructed in `_holder`. No production change if Task 2 and Task 5 are done. This task is the test and the holder wiring in the test only.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_api_fresh_process.py -q`

Expected: PASS. The existing approve-to-`pr_created` assertions still pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_api_fresh_process.py
git commit -m "$(cat <<'EOF'
test: list a request from a reconstructed process

EOF
)"
```

### Task 10: Document the index

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/roadmap.md`
- Do not modify: `tests/unit/docs/test_operator_ui_docs.py` unless an added sentence removes a locked sentence. The existing test must stay green without edits.

**Interfaces:**
- Consumes: locked sentences already in those docs
- Produces: additive sentences

- [ ] **Step 1: Confirm the new sentences are absent**

```bash
grep -n "GET /api/v1/requests lists" docs/api.md || echo ABSENT
```

Expected: `ABSENT`

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q`

Expected: PASS before the edit.

- [ ] **Step 2: Write the docs**

In `docs/api.md`, after the paragraph that starts `The UI renders the public request DTO only.`, add:

```markdown
`GET /api/v1/requests` lists the newest checkpointed requests. The index stores the request id and the server creation time. Workflow status, approval availability, security status, and name are read from the checkpoint when the list is built. The list does not include checkpoints created before the index existed; those requests remain available at `GET /api/v1/requests/{request_id}`. A failed index write does not change the create response. The list is not authentication and does not make the API safe for public Internet exposure. Enumeration discloses more to anyone who can reach the port.
```

In `docs/roadmap.md`, after the Batch 32 section and before `## Not yet started`, add:

```markdown
## Batch 33 — durable request index (complete)

The local operator UI can list checkpointed requests from `state.db`.
The LangGraph checkpoint remains the workflow authority. The index is
not backfilled, not an event log, and not an authentication boundary.
The design is
`docs/superpowers/specs/2026-09-29-batch33-design.md`. The plan is
`docs/superpowers/plans/2026-09-29-batch33-durable-request-index.md`.
```

Mark the heading complete only in the same commit as the finished implementation, which this task is. Do not claim Docker or auth changed.

- [ ] **Step 3: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/api.md docs/roadmap.md
git commit -m "$(cat <<'EOF'
docs: describe the durable request index

EOF
)"
```

### Task 11: Regression

**Files:**
- No planned production edits.

- [ ] **Step 1: Run the frontend checks**

From `ui/`:

```bash
npm test
npm run build
npx playwright test
```

Expected: Vitest passes, the production build passes, Playwright passes 2 tests.

- [ ] **Step 2: Run the Python checks**

From the repository root:

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: pytest passes. Ruff passes. `git diff --check` prints nothing.

- [ ] **Step 3: Confirm the diff boundary**

```bash
git diff --name-only 5618c2027da15cc5847685589609688e4a31d007...HEAD
```

Expected names stay in `src/iac_agent/persistence/request_index.py`, `src/iac_agent/app/service.py`, `src/iac_agent/app/composition.py`, `src/iac_agent/api/schemas.py`, `src/iac_agent/api/project.py`, `src/iac_agent/api/routes.py`, `ui/`, `tests/unit/`, `tests/integration/test_api_fresh_process.py`, `tests/browser/serve_fake_ui.py`, `docs/api.md`, `docs/roadmap.md`, and the Batch 33 design and plan. If `Dockerfile`, `compose.yaml`, `.github/`, or `src/iac_agent/graph/` appears, stop.

- [ ] **Step 4: Commit**

No commit when the tree is clean and the checks pass.

## Self-review

Spec coverage:

- Stored fields, derived fields, insert-after-invoke, idempotent insert, 422 limits, newest-only order, stale omission, no backfill, no `SqliteSaver.list`, UI copy, security negatives, and fresh-process durability each have a task.
- `RequestResponse` is not given new fields.
- Docker is explicitly not a task. The fresh-process test is the replacement proof.
- Clarification stays unindexed because `record` is only on `IacApplication.submit`, which that path does not call. Task 2 asserts `invoke` failure does not record. A clarification unit already exists in `tests/unit/api/test_routes.py` and must stay green in Task 4's regression pytest.

Placeholder scan: no task defers the schema, the status code, or the omission rule.

Type consistency: `list_requests`, `project_list_item`, `IndexedRequest`, `open_request_index`, and `RequestListItem` use the same names in every task.

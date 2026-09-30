# Batch 34 Operator Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require one in-memory operator secret on every `/api/v1/requests` route, and leave health, readiness, and the UI shell anonymous.

**Architecture:** `IAC_AGENT_OPERATOR_SECRET` is a `SecretStr` loaded beside the GitHub token, not a field of `ApplicationConfig`. Operator routes reject a missing or wrong `Authorization: Bearer` value with one 401 body before any application call. The React shell holds the secret in component state and attaches that header only on operator API calls.

**Tech Stack:** Python 3.12, FastAPI, pytest, React 19, Vitest, Playwright 1.63, ruff.

## Global Constraints

- One operator secret. No OAuth, OIDC, Cognito, Auth0, GitHub login, JWT issuance, users, roles, RBAC, or tenants.
- This is bootstrap authentication for the current single-operator local architecture. It is not the final identity architecture.
- Authenticate `POST /api/v1/requests`, `GET /api/v1/requests`, `GET /api/v1/requests/{request_id}`, and `POST /api/v1/requests/{request_id}/approval`.
- Leave anonymous: `GET /health`, `GET /ready`, static assets, and SPA routes (`GET /`, `GET /requests/{request_id}` as HTML).
- 401 body is exactly `{"error":"unauthenticated","message":"Authentication is required."}`. No `request_id`. Missing, malformed, and wrong credentials share that body.
- Do not call application code before authentication succeeds. Do not reveal whether a request id exists.
- Transport is `Authorization: Bearer <secret>` only. No query parameter, cookie, or workflow body field.
- Browser memory only. No `localStorage`, `sessionStorage`, `IndexedDB`, cookies, or durable cache. Reload clears the secret.
- No persistence schema change. Do not modify checkpoint state, `request_index`, `RequestResponse`, or `RequestListItem`. Do not add `approved_by`, actor, principal, subject, owner, or tenant storage.
- Approval semantics stay `approve` / `reject`, including 409 reconciliation.
- Compose stays `127.0.0.1:8000:8000`. Do not change bind policy, TLS, CORS, Docker topology, or remote runtime.
- Do not decouple GitHub/OpenAI startup. That debt stays independent.
- Variable name: `IAC_AGENT_OPERATOR_SECRET`. No repository default. No committed value. No log or response echo. No `VITE_` variable. No real value in the image `ENV`.
- Compare secrets with `hmac.compare_digest` on UTF-8 bytes.
- Missing or blank configuration fails startup with `MissingConfigurationError` that names the variable and not the value.
- No `terraform apply` or `terraform destroy`. No AWS, OpenAI, Langfuse, or GitHub mutation.
- Create commits with `git commit-tree` and `git reset --soft`. Do not amend. Do not add attribution trailers.
- Deterministic checks stay: `pytest -m "not real_tool and not real_llm and not docker"`, `ruff check .`, `git diff --check`, and from `ui/`: `npm test`, `npm run build`, `npx playwright test`.

---

## File map

- Create `src/iac_agent/api/operator_auth.py`: load nothing from the environment; parse `Authorization` and compare it to a `SecretStr`.
- Modify `src/iac_agent/app/config.py`: `load_operator_secret_from_env`.
- Modify `src/iac_agent/api/app.py`: lifespan loads the secret onto `app.state` when it builds the holder. `create_app` accepts an explicit secret for tests.
- Modify `src/iac_agent/api/routes.py`: call the check before every operator route body.
- Modify `ui/src/api/client.ts`: optional in-memory bearer on `/api/v1` only.
- Modify `ui/src/app.tsx`: credential field, memory state, clear on 401.
- Modify `.env.example`, `docs/api.md`, `docs/roadmap.md`.
- Modify `tests/unit/docs/test_operator_ui_docs.py` so it locks the new sentences instead of "The operator UI does not add authentication."
- Modify `tests/browser/serve_fake_ui.py` and `ui/e2e/*.spec.ts` so browser tests enter the secret.
- Do not modify `request_index.py`, `schemas.py` success models, `approval.py`, `compose.yaml` publish ports, or `Dockerfile` `ENV` / `USER`.

## Gate A — configuration and HTTP enforcement

### Task 1: Operator secret loader

**Files:**
- Modify: `src/iac_agent/app/config.py`
- Test: `tests/unit/app/test_config.py`

**Interfaces:**
- Produces: `load_operator_secret_from_env(env: Mapping[str, str] | None = None) -> SecretStr`

- [ ] **Step 1: Write the failing test**

Assert three behaviors next to the existing GitHub token tests:

- `{}` and `{ "IAC_AGENT_OPERATOR_SECRET": "" }` and a whitespace-only value raise `MissingConfigurationError`.
- The exception text contains `IAC_AGENT_OPERATOR_SECRET` and does not contain the supplied secret.
- A non-empty value returns `SecretStr` whose `repr` and `str` hide the value, while `get_secret_value()` returns it.
- `ApplicationConfig` field names still do not include the secret.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/python -m pytest tests/unit/app/test_config.py -q -k operator_secret`

Expected: FAIL because `load_operator_secret_from_env` does not exist.

- [ ] **Step 3: Minimum implementation**

Add the loader beside `load_github_token_from_env`. Read `IAC_AGENT_OPERATOR_SECRET`. Reject missing, empty, and whitespace-only values. Return `SecretStr`. Do not add a field to `ApplicationConfig`. Do not give a default.

- [ ] **Step 4: GREEN**

Run the same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

`test: require an operator secret with no default`

### Task 2: Reject anonymous and invalid operator calls before lookup

**Files:**
- Create: `src/iac_agent/api/operator_auth.py`
- Modify: `src/iac_agent/api/routes.py`
- Modify: `src/iac_agent/api/app.py` (`create_app` stores the test secret on `app.state`)
- Test: `tests/unit/api/test_operator_auth.py`

**Interfaces:**
- Consumes: a `SecretStr` on `app.state.operator_secret`
- Produces: `authenticate_operator(request) -> JSONResponse | None`. `None` means the caller may proceed. The 401 helper returns the exact body above.

- [ ] **Step 1: Write the failing test**

Build `create_app(holder=fake, operator_secret=SecretStr("test-operator-secret"))`. The fake records `submit`, `list_requests`, `read`, and `resume` calls.

Assert:

- anonymous POST create, GET list, GET detail, and POST approval each return 401 with the exact JSON body and do not call the fake
- `Authorization: Bearer wrong` does the same
- `Authorization: Basic test-operator-secret` does the same
- detail and approval for an unknown id, without a credential, are 401 and not 404
- the response text does not contain the configured secret or the wrong secret
- `caplog` text for these calls does not contain the secret

- [ ] **Step 2: RED**

Run: `.venv/bin/python -m pytest tests/unit/api/test_operator_auth.py -q`

Expected: FAIL because the routes still return their current anonymous behavior, or because `operator_secret` is not a `create_app` argument yet.

- [ ] **Step 3: Minimum implementation**

Parse `Authorization`. Accept only a scheme of `Bearer` plus one non-empty token. Compare with `hmac.compare_digest` on UTF-8 bytes. On any failure, return 401 and do not read the path id. Call this as the first line of each of the four route functions. Store `operator_secret` from `create_app` onto `app.state`. If it is missing, fail closed with the same 401.

- [ ] **Step 4: GREEN**

Re-run the new test file. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: require the operator secret on request routes`

### Task 3: Preserve authenticated behavior and anonymous probes

**Files:**
- Modify: `src/iac_agent/api/app.py` lifespan
- Modify: existing API tests that call `/api/v1/requests` so they send `Authorization: Bearer <secret>`
- Test: extend `tests/unit/api/test_operator_auth.py`, `tests/unit/api/test_app.py`, and `tests/unit/api/test_ui_static.py`

**Interfaces:**
- Consumes: `load_operator_secret_from_env`
- Produces: production lifespan sets `app.state.operator_secret` before it yields. Injected-holder tests do not read the process environment.

- [ ] **Step 1: Write the failing tests**

Add tests that:

- a valid bearer preserves create, list, detail, and approval, including HTTP 409 approval conflict and `request_not_found` for a missing id after auth
- an authenticated invalid request id is still 400 `invalid_request_id`
- an authenticated invalid list limit is still 422
- `/health` and `/ready` stay anonymous and keep their current status codes
- `GET /` and `GET /requests/{request_id}` still return the UI shell without a credential when `ui_dist` is mounted
- lifespan, given an env missing `IAC_AGENT_OPERATOR_SECRET` and a null holder, fails before serving; the error names the variable and not a secret value
- a response body and log record still omit the secret

Do not weaken existing list-projection tests. They must keep proving the six list fields and the absence of plan addresses, finding messages, workspace paths, and GitHub coordinates. Give those clients the bearer so they still reach the projection.

- [ ] **Step 2: RED**

Run: `.venv/bin/python -m pytest tests/unit/api/test_operator_auth.py tests/unit/api/test_routes.py tests/unit/api/test_request_list_route.py tests/unit/api/test_approval.py tests/unit/api/test_app.py tests/unit/api/test_ui_static.py -q`

Expected: existing route tests FAIL with 401 until they send the header. New preservation tests FAIL until lifespan and the authenticated paths are wired.

- [ ] **Step 3: Minimum implementation**

In the lifespan branch that builds the holder, call `load_operator_secret_from_env()` and store it before `yield`. Update the shared test app factory used by route tests to pass a fixed `SecretStr` and send the matching bearer. Do not skip authentication when the holder is injected. Do not change success DTO models.

- [ ] **Step 4: GREEN**

Re-run the command in Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

`test: keep probes anonymous and authenticated request behavior`

## Gate B — typed client and in-memory credential state

### Task 4: Client sends the bearer only on operator calls

**Files:**
- Modify: `ui/src/api/client.ts`
- Test: `ui/src/api/client.test.ts`

**Interfaces:**
- Consumes: nothing from the server beyond the 401 body
- Produces: `new ApiClient(fetchImpl, { operatorSecret })`. `submit`, `getRequest`, `decide`, and `listRequests` set `Authorization: Bearer <secret>` when the secret is non-empty. `health` and `ready` do not. A 401 maps through the existing HTTP error shape with `error: "unauthenticated"`.

- [ ] **Step 1: Write the failing test**

Drive a fake `fetch`. Assert the header on the four operator methods, its absence on the two probes, and that a 401 becomes `{ kind: "http", status: 401, error: "unauthenticated" }`. Assert the secret string is not copied into the thrown or returned message beyond the header the test itself inspects.

- [ ] **Step 2: RED**

Run from `ui/`: `npm test -- src/api/client.test.ts`

Expected: FAIL because the constructor does not accept the secret and the header is absent.

- [ ] **Step 3: Minimum implementation**

Add the optional secret argument. Merge the header inside `request` and `list` only. Leave `probe` unchanged.

- [ ] **Step 4: GREEN**

Re-run the client test. Expected: PASS.

- [ ] **Step 5: Commit**

`feat(ui): send the operator secret on API calls`

### Task 5: In-memory credential entry

**Files:**
- Modify: `ui/src/app.tsx`
- Modify: `ui/src/styles.css` only if the field needs the existing overflow-wrap rules
- Test: `ui/src/app.test.tsx`

**Interfaces:**
- Consumes: `ApiClient` constructed with the current in-memory secret
- Produces: a form labeled for the operator secret. Continue stores it in React state. Compose and request pages render only after that. Reload of the component starts empty. No identity heading.

- [ ] **Step 1: Write the failing test**

Render `App` with a fake client. Before entry, compose and recent-request fetches are not sent. After typing the secret and continuing, `listRequests` runs with a client that received that secret. Unmount and render again: the field is empty and no storage key was written. Spy on `window.localStorage`, `sessionStorage`, and `indexedDB` and assert they are not called. A later 401 from the client clears the field. Assert the words profile, role, and tenant are absent.

- [ ] **Step 2: RED**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: FAIL because the credential field does not exist and the existing pages render immediately.

- [ ] **Step 3: Minimum implementation**

Hold `string | null` in `App`. While it is null, show the field and still render `HealthIndicator` so probes stay anonymous. When it is set, construct the client with that secret and render the current route. If a child reports 401, set the state back to null. Do not write storage. Do not add a cookie.

- [ ] **Step 4: GREEN**

Re-run the app test. Expected: PASS.

Also run `npm test` and `npm run build` from `ui/`. Expected: PASS. `npm run build` is the typecheck; do not run `npx tsc` alone.

- [ ] **Step 5: Commit**

`feat(ui): keep the operator secret in memory`

## Gate C — operator journeys and approval invariants

### Task 6: Recent requests and approval after authentication

**Files:**
- Modify: `ui/src/pages/compose-page.test.tsx`
- Modify: `ui/src/pages/request-page.test.tsx`
- Modify: page components only if they must surface a 401 to `App`
- Test: those page tests, plus the existing approval API tests already updated in Task 3

**Interfaces:**
- Consumes: the in-memory client from Task 5
- Produces: no new API fields. Recent requests still calls `listRequests()` with no query string. Approval still posts `{"decision":"approve"}` or `reject`.

- [ ] **Step 1: Write or adjust the failing tests**

With a secret already in memory:

- Recent requests still renders one indexed row, the empty-index copy, and the encoded link
- the list failure path still uses the error banner and leaves New request usable
- approval confirmation still posts the decision
- a 409 still replaces the view with the server request
- a 401 from list or approval clears the credential state

Assert again that the pages do not touch `localStorage`, `sessionStorage`, or `indexedDB`.

- [ ] **Step 2: RED**

Run from `ui/`: `npm test -- src/pages/compose-page.test.tsx src/pages/request-page.test.tsx`

Expected: FAIL where the pages assume an unauthenticated client or do not report 401 upward.

- [ ] **Step 3: Minimum implementation**

Thread a 401 callback from the pages to `App`. Do not change list item shape, polling of the detail view, or approval request JSON.

- [ ] **Step 4: GREEN**

Re-run the page tests. Expected: PASS.

- [ ] **Step 5: Commit**

`test(ui): keep recent requests and approval behind the operator secret`

### Task 7: Browser journeys at 390px

**Files:**
- Modify: `tests/browser/serve_fake_ui.py`
- Modify: `ui/e2e/recent-requests.spec.ts`, `ui/e2e/approve.spec.ts`, `ui/e2e/conflict.spec.ts`

**Interfaces:**
- Consumes: the same bearer the UI sends
- Produces: the fake API returns the exact 401 body without the bearer, and the existing fake catalog with it. Playwright types the secret into the field before the current clicks.

- [ ] **Step 1: Write the failing spec step**

At the start of each spec, fill the operator-secret field and continue. Keep `recent-requests.spec.ts` at 390×800 and its no-horizontal-overflow assertion. The credential field must be visible and usable at that width. Anonymous calls from the spec, if any, are not required; the fake must still 401 a request that omits the header so a unit or fake test covers that.

- [ ] **Step 2: RED**

Run from `ui/`: `npx playwright test`

Expected: FAIL because the specs do not fill the field, or the fake ignores the header and the UI stays on the field after a 401.

- [ ] **Step 3: Minimum implementation**

Teach the fake the test secret and the 401 body. Do not change the `req-indexed` or `req-browser` fixtures except to require the header before those handlers. Delete `ui/test-results` after the run. Do not commit it.

- [ ] **Step 4: GREEN**

Re-run Playwright. Expected: 3 passed.

- [ ] **Step 5: Commit**

`test(ui): sign the browser operator journeys in memory`

## Gate D — docs and final validation

### Task 8: Document the boundary without widening it

**Files:**
- Modify: `docs/api.md`, `docs/roadmap.md`, `.env.example`
- Modify: `tests/unit/docs/test_operator_ui_docs.py`

**Interfaces:**
- Consumes: the closed contract in `docs/superpowers/specs/2026-09-29-batch34-design.md`
- Produces: docs that replace "The operator UI does not add authentication." with sentences that state the bearer requirement, the anonymous probes and shell, the in-memory reload behavior, and that public exposure is still not approved. Roadmap gains a Batch 34 complete section and keeps RBAC, tenants, and public deployment under not started. `.env.example` has `IAC_AGENT_OPERATOR_SECRET=` with no value.

- [ ] **Step 1: Write the failing doc test**

Change `test_api_doc_describes_the_operator_ui` so it requires the new authentication sentences and no longer requires "The operator UI does not add authentication." Keep the sentence that `0.0.0.0` inside the container is not authentication, the public-exposure refusal, the probe sentence, and the ban on `Co-Authored-By` and `Made with Cursor` in those docs. Keep the roadmap assertions that public deployment is not started.

- [ ] **Step 2: RED**

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q`

Expected: FAIL because `docs/api.md` still says the UI does not add authentication.

- [ ] **Step 3: Minimum implementation**

Update the two docs and `.env.example`. State that GitHub and OpenAI are still required before the process serves, and that this is separate from operator authentication. Do not edit `compose.yaml` or `Dockerfile`.

- [ ] **Step 4: GREEN**

Re-run the doc test. Expected: PASS.

- [ ] **Step 5: Commit**

`docs: document the operator authentication boundary`

### Task 9: Final regression

**Files:** none, unless a check fails and the fix belongs to an earlier task. Fix it with a new commit. Do not amend.

- [ ] **Step 1: Run the repository checks**

From `ui/`:

- `npm test`
- `npm run build`
- `npx playwright test`

From the repository root:

- `.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q`
- `.venv/bin/ruff check .`
- `git diff --check`

- [ ] **Step 2: Confirm the negative space**

`git diff origin/main --stat` includes no changes to `request_index.py`, checkpoint modules, `schemas.py` success models, `approval.py`, `compose.yaml` ports, or Dockerfile `ENV`. Search the diff for `terraform apply`, `terraform destroy`, `localStorage.setItem`, `VITE_`, and a committed secret value. None of those should be introduced.

- [ ] **Step 3: Do not push**

Leave the branch unpublished until a separate publication review.

## Expected production files

- `src/iac_agent/app/config.py`
- `src/iac_agent/api/operator_auth.py`
- `src/iac_agent/api/app.py`
- `src/iac_agent/api/routes.py`
- `ui/src/api/client.ts`
- `ui/src/app.tsx`
- `ui/src/styles.css` only if layout requires it
- `.env.example`
- `docs/api.md`
- `docs/roadmap.md`

## Expected tests

- `tests/unit/app/test_config.py`
- `tests/unit/api/test_operator_auth.py`
- updates in `tests/unit/api/test_routes.py`, `test_request_list_route.py`, `test_approval.py`, `test_app.py`, `test_ui_static.py`
- `ui/src/api/client.test.ts`
- `ui/src/app.test.tsx`
- `ui/src/pages/compose-page.test.tsx`
- `ui/src/pages/request-page.test.tsx`
- `tests/browser/serve_fake_ui.py`
- `ui/e2e/recent-requests.spec.ts`, `approve.spec.ts`, `conflict.spec.ts`
- `tests/unit/docs/test_operator_ui_docs.py`

## Remaining risks

- Existing route tests will all 401 until Task 3 updates their helper. That is expected, and it is part of the gate.
- A log formatter that prints raw headers would leak the bearer. The new tests must read captured logs.
- `hmac.compare_digest` reveals length mismatch timing in the general case. The values are still not logged, and the HTTP body stays identical.
- The in-memory secret disappears on reload. That is the approved lifetime, and the UI must make the field obvious.
- Startup still fails without GitHub and OpenAI. A missing operator secret is a different error and must name `IAC_AGENT_OPERATOR_SECRET`.

## Deviations from the discovery draft

The discovery left the transport and the browser lifetime open. This plan closes them: `Authorization: Bearer`, and React memory only. Approval actor persistence stays a follow-on batch. Lifespan decoupling stays out.

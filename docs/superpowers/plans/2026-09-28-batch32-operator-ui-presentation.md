# Batch 32 Operator UI Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing local operator UI scannable as a review surface without changing workflow, API, or trust-boundary behavior.

**Architecture:** Keep the React tree from Batch 31. Add a hand-written presentation primitive that shows a field label and the raw server value together. Restyle the composer, request page, plan counts, findings table, and approval dialog with CSS custom properties. Do not add a data layer, a route, or a DTO field.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, Playwright. No new packages.

**Spec:** `docs/superpowers/specs/2026-09-28-batch32-design.md` (closed, commit `0647b695bcfa7b63bfd88224954e784be1a43c18`).

## Global Constraints

- Presentation only. No new HTTP route, public DTO field, workflow state, or infrastructure resource.
- Browser calls stay `POST /api/v1/requests`, `GET /api/v1/requests/{request_id}`, `POST /api/v1/requests/{request_id}/approval`, `GET /health`, and `GET /ready`. `ApiClient` remains the only fetch boundary.
- Do not render Terraform source, raw plan JSON, resource addresses, finding `resource`, finding `message`, `WorkflowError.message`, checkpoint contents, workspace paths, tokens, or GitHub owner, repository, branch, or base branch.
- Server enums stay in the DOM. Companion text may only turn underscores into spaces and capitalize the first character. Example: visible text `Awaiting approval` beside visible text `awaiting_approval`. Do not invent a second state machine.
- `approval_available` still controls whether approval controls render. Approve still opens the existing confirmation sentence and sends nothing until Confirm approval. Cancel still returns focus to Approve and sends nothing. Reject still sends immediately and does not open the dialog.
- HTTP 409 still replaces the view with the embedded `request`. The alert text stays `This request cannot accept that decision.`
- Poll only `pending`, `running`, and `approved`, every 5000 ms, at most 12 poll GETs. Do not poll `awaiting_approval`, `rejected`, `blocked`, `error`, or `pr_created`.
- No `localStorage`, `sessionStorage`, `IndexedDB`, WebSockets, SSE, Redux, Zustand, XState, or TanStack Query.
- No Tailwind, Material UI, Chakra, shadcn, Bootstrap, or any new component or design-system dependency. No new npm package.
- Destructive changes keep the sentence `Destructive change detected.` Color, weight, and border may only supplement that sentence.
- `/health` copy stays `API process responded.` or `API process did not respond.`
- `/ready` copy stays `Application process is ready to accept requests.` or `Application process is not ready.`
- The h1 text stays `IaC Agent Platform`. `ui/index.html` title stays `IaC Agent Platform`.
- Error alert text stays exactly the client message. Do not prefix the alert, or `app.test.tsx` exact match `/^Invalid request\.$/` fails.
- `terraform_apply` stays `not_executed`. The sentence `Terraform apply was not executed.` stays. No terraform apply or destroy.
- Compose publication, Docker, CI, Python production code, and public schemas stay unchanged.
- Do not claim WCAG conformance. Accessibility acceptance is the checks in the Accessibility section below.
- No attribution trailers. If `git commit` appends `Co-Authored-By`, `Generated-By`, `Made with Cursor`, `Cursor`, `Claude`, or `Anthropic`, create the commit with `git commit-tree` and `git reset --soft` instead of amending.
- No real AWS, OpenAI, GitHub, or Langfuse calls.

If an implementation step seems to require a Python, schema, Docker, compose, Terraform, or CI edit, stop. That is a design conflict. Do not broaden the batch.

## File map

| File | Responsibility |
|---|---|
| `ui/src/styles.css` | Tokens, shell, panels, plan counts, table, dialog, focus, narrow layout. |
| `ui/src/app.tsx` | Shell header, page heading order, unknown-route heading. |
| `ui/src/components/health-indicator.tsx` | Labeled API and readiness facts. Exact sentences unchanged. |
| `ui/src/components/authoritative-value.tsx` | Field label, caption, and raw server value. Create in Task 4. |
| `ui/src/pages/compose-page.tsx` | Composer hierarchy and unsaved-result panel. |
| `ui/src/components/request-form.tsx` | Existing labels. Class hooks only if needed. |
| `ui/src/components/open-request.tsx` | Existing labels. Class hooks only if needed. |
| `ui/src/components/request-summary.tsx` | Request identity definition list. |
| `ui/src/components/workflow-status.tsx` | Workflow facts, error stage and type, pull-request URL. |
| `ui/src/components/plan-summary.tsx` | Add, Change, and Destroy as a labeled list. |
| `ui/src/components/findings.tsx` | Caption and column scope. Public cells only. |
| `ui/src/components/error-banner.tsx` | Existing alert and focus. CSS class only. |
| `ui/src/pages/request-page.tsx` | Review heading, loading status, polling status. Poll logic unchanged. |
| `ui/src/components/approval-panel.tsx` | Decision region, dialog initial focus, reject explanation. |
| `ui/src/app.test.tsx` | Shell, health labels, composer headings. Modify. |
| `ui/src/components/authoritative-value.test.tsx` | Caption rule. Create in Task 4. |
| `ui/src/components/projection.test.tsx` | Summary, workflow, plan, findings structure. Modify. |
| `ui/src/pages/request-page.test.tsx` | Loading and polling status text. Modify. |
| `ui/src/components/approval-panel.test.tsx` | Dialog focus and reject copy. Modify. |
| `ui/e2e/approve.spec.ts` | Narrow viewport plus semantic review assertions. Modify. |
| `ui/e2e/conflict.spec.ts` | Review heading remains after 409. Modify. |
| `docs/api.md` | One additive presentation sentence. |
| `docs/roadmap.md` | Batch 32 complete note. Do not remove the Batch 31 heading. |

Do not modify: `ui/src/api/types.ts`, `ui/src/api/client.ts`, `ui/src/api/polling.ts`, `ui/src/router.ts`, `ui/package.json`, `ui/index.html`, `src/iac_agent/`, `Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`, `tests/browser/serve_fake_ui.py`.

## Accessibility acceptance

Do not claim WCAG compliance. The batch is accepted when tests prove these behaviors:

- `h1` is `IaC Agent Platform`. Page sections use `h2`. Review blocks use `h3`. Component list uses `h4` only when components exist.
- Composer fields keep their labels: `Infrastructure request` and `Request id`.
- Approve, Reject request, Confirm approval, Cancel, Submit request, Open request, and Refresh remain buttons with those accessible names.
- The confirmation dialog's accessible name remains the existing confirmation sentence.
- Opening the dialog moves focus to Cancel. Cancel returns focus to Approve.
- The error banner remains `role="alert"` and receives focus. Its text is only the client message.
- Loading and polling use `role="status"`.
- Findings use a table with caption `Security findings` and `scope="col"` headers Policy, Status, and Severity.
- Plan counts are a description list with the terms Add, Change, and Destroy.
- Workflow status, stage, security status, outcome, and finding status and severity remain visible as the server sent them.
- The destructive sentence is present whenever `destructive_change_detected` is true, including if styles were ignored.
- At a 390px viewport, the existing approve Playwright path still reaches the pull-request link.
- Focusable controls use `:focus-visible` in `styles.css`. Do not assert outline pixels.

---

## Gate A — visual foundation and shell

### Task 1: Design tokens and application shell

**Files:**
- Modify: `ui/src/styles.css`
- Modify: `ui/src/app.tsx`
- Test: `ui/src/app.test.tsx`

**Interfaces:**
- Consumes: `App` props `client`, `navigate`, `pathname`
- Produces: shell header classes `.shell-header`; custom properties listed below; `h2` text `Page not found.` for unknown routes

- [ ] **Step 1: Write the failing test**

Add this test to the `operator shell` describe in `ui/src/app.test.tsx`:

```tsx
  it("uses a page heading for an unknown route", () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/missing" />);
    expect(screen.getByRole("heading", { level: 1, name: "IaC Agent Platform" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Page not found." })).toBeInTheDocument();
    expect(screen.getByText("Local operator console. Review the server response before approving a request.")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: FAIL because the unknown route is a paragraph, not an `h2`, and the console sentence is absent.

- [ ] **Step 3: Write minimal implementation**

Replace `ui/src/styles.css` with:

```css
:root {
  --color-text: #1c1917;
  --color-muted: #44403c;
  --color-surface: #fafaf9;
  --color-panel: #ffffff;
  --color-border: #d6d3d1;
  --color-focus: #1d4ed8;
  --color-danger-text: #7f1d1d;
  --color-danger-border: #b91c1c;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --font-sans: ui-sans-serif, system-ui, sans-serif;
  --font-mono: ui-monospace, sfmono-regular, menlo, monospace;
  --measure: 72rem;
  --line: 1.45;
  color: var(--color-text);
  background: var(--color-surface);
  font-family: var(--font-sans);
  line-height: var(--line);
}

body {
  margin: 0;
}

main {
  box-sizing: border-box;
  max-width: var(--measure);
  margin: 0 auto;
  padding: var(--space-5);
}

.shell-header {
  margin-bottom: var(--space-5);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.shell-header p {
  max-width: 40rem;
  color: var(--color-muted);
}

h1,
h2,
h3,
h4 {
  line-height: 1.25;
  margin: 0 0 var(--space-3);
}

h1 {
  font-size: 1.5rem;
}

h2 {
  font-size: 1.25rem;
}

h3,
h4 {
  font-size: 1rem;
}

label,
button {
  font: inherit;
}

textarea,
input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin: var(--space-2) 0 var(--space-4);
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  background: var(--color-panel);
  font: inherit;
}

textarea {
  min-height: 8rem;
}

button {
  margin: 0 var(--space-2) var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  background: var(--color-panel);
  color: var(--color-text);
}

button:disabled {
  color: var(--color-muted);
}

:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

code,
.enum {
  font-family: var(--font-mono);
  font-size: 0.95em;
}

.banner {
  margin: var(--space-4) 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-danger-border);
  color: var(--color-danger-text);
  background: var(--color-panel);
}

.panel {
  margin: 0 0 var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  background: var(--color-panel);
}

dl {
  margin: 0;
}

dt {
  font-weight: 650;
}

dd {
  margin: 0 0 var(--space-3);
}

@media (max-width: 40rem) {
  main {
    padding: var(--space-4);
  }
}
```

Replace the return in `ui/src/app.tsx` with:

```tsx
  return (
    <main>
      <header className="shell-header">
        <h1>IaC Agent Platform</h1>
        <p>Local operator console. Review the server response before approving a request.</p>
        <HealthIndicator client={client} />
      </header>
      {route.name === "compose" ? <ComposePage client={client} navigate={navigate} /> : null}
      {route.name === "request" ? (
        <RequestPage client={client} requestId={route.requestId} />
      ) : null}
      {route.name === "unknown" ? <h2>Page not found.</h2> : null}
    </main>
  );
```

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: PASS, including the existing composer tests.

- [ ] **Step 5: Commit**

```bash
git add ui/src/styles.css ui/src/app.tsx ui/src/app.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): add the operator shell and design tokens

EOF
)"
```

If the commit message gains an attribution trailer, recreate it with `git commit-tree` and do not amend.

### Task 2: Health and readiness presentation

**Files:**
- Modify: `ui/src/components/health-indicator.tsx`
- Test: `ui/src/app.test.tsx`

**Interfaces:**
- Consumes: `client.health()` and `client.ready()` results already used by `HealthIndicator`
- Produces: definition terms `API` and `Readiness` whose descriptions are the existing sentences

- [ ] **Step 1: Write the failing test**

Add this test to `operator shell` in `ui/src/app.test.tsx`:

```tsx
  it("labels health and readiness without changing the sentences", async () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
    expect(await screen.findByRole("term", { name: "API" })).toBeInTheDocument();
    expect(screen.getByText("API process responded.")).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Readiness" })).toBeInTheDocument();
    expect(screen.getByText("Application process is ready to accept requests.")).toBeInTheDocument();
  });
```

Assert the terms and the existing sentences separately. Do not require the description's accessible name to equal the sentence; jsdom does not name a `definition` from its text.

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: FAIL because health is two spans inside a paragraph, so the terms are missing.

- [ ] **Step 3: Write minimal implementation**

Replace the return in `ui/src/components/health-indicator.tsx` with:

```tsx
  return (
    <section aria-label="Process status">
      <dl>
        <div>
          <dt>API</dt>
          <dd>{health}</dd>
        </div>
        <div>
          <dt>Readiness</dt>
          <dd>{ready}</dd>
        </div>
      </dl>
    </section>
  );
```

Leave the effect and the sentence strings unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: PASS. The older test that uses `findByText("API process responded.")` still passes.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/health-indicator.tsx ui/src/app.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): label health and readiness

EOF
)"
```

---

## Gate B — request composer and workflow review surface

### Task 3: Composer and open-request presentation

**Files:**
- Modify: `ui/src/pages/compose-page.tsx`
- Modify: `ui/src/components/request-form.tsx`
- Modify: `ui/src/components/open-request.tsx`
- Test: `ui/src/app.test.tsx`

**Interfaces:**
- Consumes: existing `RequestForm` and `OpenRequest` props
- Produces: `h2` `New request`, `h3` `Open a saved request`, `h3` `Unsaved result`. Outcome text remains visible. The sentences `This result is not saved. Refreshing clears it.` and `This request was not saved.` stay exact.

- [ ] **Step 1: Write the failing test**

Add this test to `operator shell` in `ui/src/app.test.tsx`:

```tsx
  it("groups the composer and the open-request control", () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
    expect(screen.getByRole("heading", { level: 2, name: "New request" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Open a saved request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Request id" })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: FAIL because those headings do not exist.

- [ ] **Step 3: Write minimal implementation**

Add `className="panel"` to the `<form>` in `ui/src/components/request-form.tsx` and in `ui/src/components/open-request.tsx`. Do not change labels, ids, or handlers.

Replace the return and `NonDurableOutcome` in `ui/src/pages/compose-page.tsx` with:

```tsx
  return (
    <section aria-labelledby="compose-heading">
      <h2 id="compose-heading">New request</h2>
      <p>Describe the infrastructure. A durable workflow opens on its own page.</p>
      <RequestForm value={draft} busy={busy} onChange={setDraft} onSubmit={() => void submit()} />
      <h3>Open a saved request</h3>
      <OpenRequest navigate={navigate} />
      {localError ? <p>{localError}</p> : null}
      {banner ? <ErrorBanner message={banner} /> : null}
      {unsaved ? <p>This request was not saved.</p> : null}
      {outcome ? <NonDurableOutcome body={outcome} /> : null}
    </section>
  );
```

```tsx
function NonDurableOutcome({ body }: { body: RequestResponse }) {
  const resolution = body.resolution;
  return (
    <section className="panel" aria-labelledby="unsaved-outcome-heading">
      <h3 id="unsaved-outcome-heading">Unsaved result</h3>
      <p>
        <span>Outcome</span> <code>{body.outcome}</code>
      </p>
      <p>This result is not saved. Refreshing clears it.</p>
      {resolution.field ? <p>{resolution.field}</p> : null}
      {resolution.reason ? <p>{resolution.reason}</p> : null}
      {resolution.detail ? <p>{resolution.detail}</p> : null}
      {resolution.allowed_values?.map((value) => (
        <p key={value}>{value}</p>
      ))}
    </section>
  );
}
```

The raw `body.outcome` stays in a `code` element. Do not replace it with a friendlier word. Field, reason, detail, and allowed values stay as their server strings so the existing clarification and unsupported tests keep passing.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/app.test.tsx`

Expected: PASS, including clarification, unsupported, blank submit, and interpreter-failure tests.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/compose-page.tsx ui/src/components/request-form.tsx ui/src/components/open-request.tsx ui/src/app.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): group the request composer

EOF
)"
```

### Task 4: Authoritative value and request summary

**Files:**
- Create: `ui/src/components/authoritative-value.tsx`
- Create: `ui/src/components/authoritative-value.test.tsx`
- Modify: `ui/src/components/request-summary.tsx`
- Test: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `RequestResponse`
- Produces:
  - `enumCaption(value: string): string`
  - `AuthoritativeValue({ label, value }: { label: string; value: string })` rendering `dt` label, a span caption, and `code` containing `value`

- [ ] **Step 1: Write the failing test**

Create `ui/src/components/authoritative-value.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthoritativeValue, enumCaption } from "./authoritative-value";

describe("authoritative value", () => {
  it("spaces an enum and keeps the server value", () => {
    expect(enumCaption("awaiting_approval")).toBe("Awaiting approval");
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="awaiting_approval" />
      </dl>,
    );
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByText("awaiting_approval")).toBeInTheDocument();
  });

  it("does not invent a word that is not in the enum", () => {
    expect(enumCaption("pr_created")).toBe("Pr created");
    expect(enumCaption("warn")).toBe("Warn");
  });
});
```

Add this test to `request projection` in `ui/src/components/projection.test.tsx`:

```tsx
  it("labels the request id and outcome and still shows the server outcome", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Request" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Request id" })).toBeInTheDocument();
    expect(screen.getByText("req-1")).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Outcome" })).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/components/authoritative-value.test.tsx src/components/projection.test.tsx`

Expected: FAIL because `authoritative-value.tsx` does not exist and the Request heading is absent.

- [ ] **Step 3: Write minimal implementation**

Create `ui/src/components/authoritative-value.tsx`:

```tsx
export function enumCaption(value: string): string {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function AuthoritativeValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <span>{enumCaption(value)}</span> <code className="enum">{value}</code>
      </dd>
    </div>
  );
}
```

Replace `ui/src/components/request-summary.tsx` with:

```tsx
import type { RequestResponse } from "../api/types";
import { AuthoritativeValue } from "./authoritative-value";

export function RequestSummary({ body }: { body: RequestResponse }) {
  const architectureMissing = body.resolution.architecture == null;
  const intentMissing = body.intent === null;
  return (
    <section className="panel" aria-labelledby="request-summary-heading">
      <h3 id="request-summary-heading">Request</h3>
      <dl>
        <div>
          <dt>Request id</dt>
          <dd>
            <code className="enum">{body.request_id}</code>
          </dd>
        </div>
        <AuthoritativeValue label="Outcome" value={body.outcome} />
        {body.resolution.name ? (
          <div>
            <dt>Name</dt>
            <dd>{body.resolution.name}</dd>
          </div>
        ) : null}
        {body.resolution.architecture ? (
          <AuthoritativeValue label="Architecture" value={body.resolution.architecture} />
        ) : null}
        {body.intent ? (
          <>
            <AuthoritativeValue label="Workload" value={body.intent.workload_type} />
            <AuthoritativeValue label="Interaction" value={body.intent.interaction_pattern} />
            <div>
              <dt>Capabilities</dt>
              <dd>{body.intent.capabilities.join(" ")}</dd>
            </div>
          </>
        ) : null}
      </dl>
      {body.resolution.components && body.resolution.components.length > 0 ? (
        <>
          <h4>Components</h4>
          <ul>
            {body.resolution.components.map((component) => (
              <li key={`${component.role}:${component.name}`}>
                <span>{component.role}</span> <span>{component.name}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {architectureMissing || intentMissing ? <p>Unavailable after reload.</p> : null}
    </section>
  );
}
```

Do not render `matched_pattern`, `image_tag_mutability`, or `scan_on_push`.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/components/authoritative-value.test.tsx src/components/projection.test.tsx src/pages/request-page.test.tsx`

Expected: PASS. The reconstructed-GET test still finds `Unavailable after reload.` and does not find `serverless_worker`, `queue_processing`, or the matched pattern.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/authoritative-value.tsx ui/src/components/authoritative-value.test.tsx ui/src/components/request-summary.tsx ui/src/components/projection.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): label the request summary

EOF
)"
```

### Task 5: Workflow facts and pull-request result

**Files:**
- Modify: `ui/src/components/workflow-status.tsx`
- Test: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `AuthoritativeValue` and `enumCaption` from Task 4
- Produces: `h3` `Workflow`; terms `Workflow status`, `Stage`, `Security status` when those fields exist; raw values in `code`; pull-request link accessible name remains the URL

- [ ] **Step 1: Write the failing test**

Add this test to `request projection` in `ui/src/components/projection.test.tsx`:

```tsx
  it("shows workflow labels beside the server enums", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Workflow" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Stage" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Security status" })).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
    expect(screen.getByText("approval")).toBeInTheDocument();
    expect(screen.getAllByText("warn").length).toBeGreaterThan(0);
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/components/projection.test.tsx`

Expected: FAIL because `Workflow` is not a heading and the terms are absent.

- [ ] **Step 3: Write minimal implementation**

Replace `ui/src/components/workflow-status.tsx` with:

```tsx
import type { RequestResponse } from "../api/types";
import { AuthoritativeValue } from "./authoritative-value";

export function WorkflowStatus({ body }: { body: RequestResponse }) {
  const workflow = body.workflow;
  const pullRequestUrl = workflow?.pull_request?.url;
  return (
    <section className="panel" aria-labelledby="workflow-heading">
      <h3 id="workflow-heading">Workflow</h3>
      {workflow ? (
        <dl>
          <AuthoritativeValue label="Workflow status" value={workflow.workflow_status} />
          {workflow.current_stage ? (
            <AuthoritativeValue label="Stage" value={workflow.current_stage} />
          ) : null}
          {workflow.security_status ? (
            <AuthoritativeValue label="Security status" value={workflow.security_status} />
          ) : null}
        </dl>
      ) : null}
      <p>Terraform apply was not executed.</p>
      <p>{body.approval_available ? "Approval available" : "Approval not available"}</p>
      {workflow?.error ? (
        <dl>
          <AuthoritativeValue label="Error stage" value={workflow.error.stage} />
          <AuthoritativeValue label="Error type" value={workflow.error.error_type} />
        </dl>
      ) : null}
      {pullRequestUrl ? (
        <p>
          <span>Pull request</span> <a href={pullRequestUrl}>{pullRequestUrl}</a>
        </p>
      ) : null}
    </section>
  );
}
```

Do not read or render `workflow.error.message`. The existing error test looks for the strings `terraform` and `RuntimeError`, which remain inside the `code` elements.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/components/projection.test.tsx src/pages/request-page.test.tsx`

Expected: PASS. The pull-request test still finds the link by the URL. The hidden error message stays absent.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/workflow-status.tsx ui/src/components/projection.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): show workflow facts beside server enums

EOF
)"
```

### Task 6: Plan count review

**Files:**
- Modify: `ui/src/components/plan-summary.tsx`
- Modify: `ui/src/styles.css`
- Test: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `PlanDTO | null`
- Produces: `h3` `Terraform plan summary`; terms Add, Change, Destroy; the sentence `Destructive change detected.` only when the boolean is true; class `panel-destructive` only as a supplement

- [ ] **Step 1: Write the failing test**

Add this test to `request projection` in `ui/src/components/projection.test.tsx`:

```tsx
  it("labels add, change, and destroy and keeps the destructive sentence", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Terraform plan summary" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Add" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Change" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Destroy" })).toBeInTheDocument();
    expect(screen.getByText("Destructive change detected.")).toBeInTheDocument();
    expect(screen.queryByText("aws_sqs_queue.hidden_address")).not.toBeInTheDocument();
  });
```

The posted fixture already has `destructive_change_detected: true` and counts 2, 1, and 0. The existing test that looks for those numbers must still pass.

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/components/projection.test.tsx`

Expected: FAIL because Add, Change, and Destroy are paragraphs, not terms, and the heading is absent.

- [ ] **Step 3: Write minimal implementation**

Replace `ui/src/components/plan-summary.tsx` with:

```tsx
import type { PlanDTO } from "../api/types";

export function PlanSummary({ plan }: { plan: PlanDTO | null }) {
  if (!plan) {
    return <p>No plan summary was returned.</p>;
  }
  const destructive = plan.destructive_change_detected;
  return (
    <section
      className={destructive ? "panel panel-destructive" : "panel"}
      aria-labelledby="plan-summary-heading"
    >
      <h3 id="plan-summary-heading">Terraform plan summary</h3>
      <dl className="plan-counts">
        <div>
          <dt>Add</dt>
          <dd>{plan.add}</dd>
        </div>
        <div>
          <dt>Change</dt>
          <dd>{plan.change}</dd>
        </div>
        <div>
          <dt>Destroy</dt>
          <dd>{plan.destroy}</dd>
        </div>
      </dl>
      {destructive ? <p className="destructive-sentence">Destructive change detected.</p> : null}
    </section>
  );
}
```

Append to `ui/src/styles.css`:

```css
.plan-counts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.plan-counts dd {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 1.25rem;
}

.panel-destructive {
  border-color: var(--color-danger-border);
}

.destructive-sentence {
  margin: var(--space-3) 0 0;
  font-weight: 650;
}

@media (max-width: 40rem) {
  .plan-counts {
    grid-template-columns: 1fr;
  }
}
```

Do not derive a new danger fact from the destroy count. The sentence follows `destructive_change_detected` only.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/components/projection.test.tsx`

Expected: PASS, including `No plan summary was returned.` when `plan` is null.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/plan-summary.tsx ui/src/styles.css ui/src/components/projection.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): structure the plan count review

EOF
)"
```

### Task 7: Security findings table

**Files:**
- Modify: `ui/src/components/findings.tsx`
- Modify: `ui/src/styles.css`
- Test: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `FindingDTO[]` with `policy_id`, `status`, and `severity` only
- Produces: table named `Security findings` by its caption; column headers Policy, Status, Severity

- [ ] **Step 1: Write the failing test**

Add this test to `request projection` in `ui/src/components/projection.test.tsx`:

```tsx
  it("names the findings table and keeps only public columns", () => {
    render(<Projection body={posted} />);
    const table = screen.getByRole("table", { name: "Security findings" });
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Policy" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Severity" })).toBeInTheDocument();
    expect(screen.getByText("SQS_ENCRYPTION")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Resource" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Message" })).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/components/projection.test.tsx`

Expected: FAIL because the table has no accessible name.

- [ ] **Step 3: Write minimal implementation**

Replace `ui/src/components/findings.tsx` with:

```tsx
import type { FindingDTO } from "../api/types";

export function Findings({ findings }: { findings: FindingDTO[] }) {
  return (
    <section className="panel" aria-labelledby="findings-heading">
      <h3 id="findings-heading">Security findings</h3>
      <table>
        <caption className="visually-hidden">Security findings</caption>
        <thead>
          <tr>
            <th scope="col">Policy</th>
            <th scope="col">Status</th>
            <th scope="col">Severity</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((finding) => (
            <tr key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
              <td>
                <code className="enum">{finding.policy_id}</code>
              </td>
              <td>
                <code className="enum">{finding.status}</code>
              </td>
              <td>
                <code className="enum">{finding.severity}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

The caption is visually hidden because the `h3` already shows the same words. The caption still names the table for assistive tech. Append to `ui/src/styles.css`:

```css
table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

Do not add a resource or message cell. Status and severity cells contain the raw server strings, not a rewritten severity scale.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/components/projection.test.tsx`

Expected: PASS. The finding-resource test still fails to find the ARN and `HIDDEN_FINDING_MESSAGE`.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/findings.tsx ui/src/styles.css ui/src/components/projection.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): name the security findings table

EOF
)"
```

### Task 8: Loading, polling, and error presentation

**Files:**
- Modify: `ui/src/pages/request-page.tsx`
- Test: `ui/src/pages/request-page.test.tsx`

**Interfaces:**
- Consumes: `shouldPoll`, `POLL_INTERVAL_MS`, `POLL_MAX_ATTEMPTS` unchanged
- Produces: `h2` `Request review`; `role="status"` text `Loading request.` only while there is no body and no banner; `role="status"` text `Checking this request.` only while `shouldPoll(status)` is true and the poll budget is not exhausted; paragraph `Automatic checks stopped.` when the budget is exhausted. Refresh button name stays `Refresh`.

- [ ] **Step 1: Write the failing test**

Add these tests to `request page` in `ui/src/pages/request-page.test.tsx`:

```tsx
  it("announces a loading status until the server body arrives", async () => {
    let resolveGet: (value: ClientResult) => void = () => {};
    const pending = new Promise<ClientResult>((resolve) => {
      resolveGet = resolve;
    });
    const getRequest = vi.fn().mockReturnValue(pending);
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(screen.getByRole("heading", { level: 2, name: "Request review" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading request.");
    resolveGet({ kind: "success", status: 200, body: reloaded });
    expect(await screen.findByText("req-1")).toBeInTheDocument();
    expect(screen.queryByText("Loading request.")).not.toBeInTheDocument();
    expect(screen.queryByText("Checking this request.")).not.toBeInTheDocument();
  });

  it("announces polling only for a pollable status and stops after the budget", async () => {
    vi.useFakeTimers();
    const pendingBody: RequestResponse = {
      ...reloaded,
      outcome: "pending",
      approval_available: false,
      workflow: { ...reloaded.workflow!, workflow_status: "pending" },
    };
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: pendingBody });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Checking this request.");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000 * 13);
    });
    expect(getRequest).toHaveBeenCalledTimes(13);
    expect(screen.getByText("Automatic checks stopped.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByText("Checking this request.")).not.toBeInTheDocument();
    vi.useRealTimers();
  });
```

`awaiting_approval` is not pollable. The existing test `does not poll awaiting approval` must still see one GET. The loading test above also asserts that `Checking this request.` is absent for `awaiting_approval`.

The interval sets `pollExhausted` when `attempts` becomes 13. Twelve ticks perform the 12 poll GETs, so the mount plus those ticks is 13 calls. The thirteenth tick stops without another GET. That is why the new test advances `5000 * 13`.

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/pages/request-page.test.tsx`

Expected: FAIL because `Request review`, `Loading request.`, and `Automatic checks stopped.` are absent.

- [ ] **Step 3: Write minimal implementation**

In `ui/src/pages/request-page.tsx`, keep both effects and `applyRead` / `onDecision` unchanged. Replace the return with:

```tsx
  const polling = shouldPoll(status) && !pollExhausted;
  return (
    <section aria-labelledby="request-review-heading">
      <h2 id="request-review-heading">Request review</h2>
      {banner ? <ErrorBanner message={banner} /> : null}
      {!body && !banner ? <p role="status">Loading request.</p> : null}
      {polling ? <p role="status">Checking this request.</p> : null}
      {body ? (
        <>
          <RequestSummary body={body} />
          <WorkflowStatus body={body} />
          <PlanSummary plan={body.workflow?.plan ?? null} />
          <Findings findings={body.workflow?.findings ?? []} />
          <ApprovalPanel body={body} client={client} onResult={onDecision} />
        </>
      ) : null}
      {pollExhausted ? (
        <>
          <p>Automatic checks stopped.</p>
          <button
            type="button"
            onClick={() => {
              setPollExhausted(false);
              void client.getRequest(requestId).then(applyRead);
            }}
          >
            Refresh
          </button>
        </>
      ) : null}
    </section>
  );
```

Do not change `POLL_INTERVAL_MS` or `POLL_MAX_ATTEMPTS`. Do not add a status that the server did not send. `ErrorBanner` stays message-only.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/pages/request-page.test.tsx src/api/polling.test.ts`

Expected: PASS. Not-found still shows `Request not found.` and does not show `pending` or `awaiting_approval`. Conflict and approve tests still pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/request-page.tsx ui/src/pages/request-page.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): show loading and polling status

EOF
)"
```

---

## Gate C — HITL and interaction polish

### Task 9: Approval panel and confirmation dialog

**Files:**
- Modify: `ui/src/components/approval-panel.tsx`
- Modify: `ui/src/styles.css`
- Test: `ui/src/components/approval-panel.test.tsx`

**Interfaces:**
- Consumes: `ApprovalPanel` props unchanged; `CONFIRM_TEXT` unchanged
- Produces: region `Approval decision`; reject sentence `Reject sends immediately and does not ask for confirmation.`; dialog initial focus on Cancel; existing button names unchanged

- [ ] **Step 1: Write the failing test**

Add this test to `approval panel` in `ui/src/components/approval-panel.test.tsx`:

```tsx
  it("moves focus into the dialog and explains that reject is immediate", async () => {
    const user = userEvent.setup();
    const decide = vi.fn();
    render(<ApprovalPanel body={body(true)} client={clientWith(decide)} onResult={vi.fn()} />);
    expect(
      screen.getByText("Reject sends immediately and does not ask for confirmation."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", {
      name: "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.",
    });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(decide).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run from `ui/`: `npm test -- src/components/approval-panel.test.tsx`

Expected: FAIL because the reject sentence is absent and Cancel is not focused when the dialog opens.

- [ ] **Step 3: Write minimal implementation**

In the open effect, after `showModal` or `setAttribute`, focus the cancel button:

```tsx
  useEffect(() => {
    if (!open) {
      return;
    }
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    dialog.querySelector<HTMLButtonElement>("[data-dialog-initial-focus]")?.focus();
  }, [open]);
```

Replace the returned section with:

```tsx
  return (
    <section className="panel decision" aria-labelledby="approval-heading" aria-busy={busy}>
      <h3 id="approval-heading">Approval decision</h3>
      <p>Reject sends immediately and does not ask for confirmation.</p>
      <button ref={approveRef} type="button" disabled={busy} onClick={() => setOpen(true)}>
        Approve
      </button>
      <button type="button" disabled={busy} onClick={() => void decide("reject")}>
        Reject request
      </button>
      {open ? (
        <dialog ref={dialogRef} aria-labelledby="approve-confirm-title">
          <p id="approve-confirm-title">{CONFIRM_TEXT}</p>
          <button type="button" data-dialog-initial-focus disabled={busy} onClick={cancel}>
            Cancel
          </button>
          <button type="button" disabled={busy} onClick={() => void decide("approve")}>
            Confirm approval
          </button>
        </dialog>
      ) : null}
    </section>
  );
```

Keep `CONFIRM_TEXT` exact. Keep `decide("reject")` on the reject button with no dialog. Keep `cancel` focusing `approveRef`. When `approval_available` is false, still `return null`.

Append to `ui/src/styles.css`:

```css
.decision {
  border-width: 2px;
}

dialog {
  max-width: 32rem;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  background: var(--color-panel);
  color: var(--color-text);
}

dialog p {
  margin-top: 0;
}
```

Do not add an icon that is the only destructive or reject signal. Do not render `approved` or `pr_created` from the panel. The parent still renders the returned body.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npm test -- src/components/approval-panel.test.tsx src/pages/request-page.test.tsx`

Expected: PASS. Cancel still returns focus to Approve. Confirm approval still calls `decide` with `approve`. Reject still calls `decide` with `reject` and the confirmation sentence stays out of the document. The in-flight test still sees disabled buttons and does not find `approved` or `pr_created` inside the panel before `onResult`.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/approval-panel.tsx ui/src/styles.css ui/src/components/approval-panel.test.tsx
git commit -m "$(cat <<'EOF'
feat(ui): present the approval decision

EOF
)"
```

---

## Gate D — acceptance and documentation

### Task 10: Playwright semantic assertions

**Files:**
- Modify: `ui/e2e/approve.spec.ts`
- Modify: `ui/e2e/conflict.spec.ts`

**Interfaces:**
- Consumes: the fake server in `tests/browser/serve_fake_ui.py`, which is not modified. Happy path plan counts are add 1, change 0, destroy 0, `destructive_change_detected` false. Finding public cells are `SQS_ENCRYPTION`, `pass`, and `high`.
- Produces: the same approve and conflict flows, plus review landmarks

- [ ] **Step 1: Write the failing test**

Replace `ui/e2e/approve.spec.ts` with:

```ts
import { expect, test } from "@playwright/test";

test("approve publishes the pull request url", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "IaC Agent Platform" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New request" })).toBeVisible();
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill(
    "build a worker that processes a queue and stores results",
  );
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByText("req-browser")).toBeVisible();
  await expect(page.getByText("awaiting_approval").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Terraform plan summary" })).toBeVisible();
  await expect(page.getByText("Add", { exact: true })).toBeVisible();
  await expect(page.getByText("1", { exact: true })).toBeVisible();
  await expect(page.getByText("Change", { exact: true })).toBeVisible();
  await expect(page.getByText("0", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Destroy", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByText("SQS_ENCRYPTION")).toBeVisible();
  await expect(page.getByText("arn:aws:sqs:us-east-1:123456789012:hidden")).toHaveCount(0);
  await expect(page.getByText("HIDDEN_FINDING_MESSAGE")).toHaveCount(0);
  await expect(page.getByText("aws_sqs_queue.hidden_address")).toHaveCount(0);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText("pr_created").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "https://example.invalid/pull/7" })).toBeVisible();
});
```

Add these expectations to `ui/e2e/conflict.spec.ts` after the rejected assertion, and keep the existing steps:

```ts
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByText("rejected").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
```

The conflict file already asserts the conflict sentence and `rejected`. Do not remove those lines. Do not add a second copy of the `rejected` assertion if the edit would duplicate it; the final test body is:

```ts
import { expect, test } from "@playwright/test";

test("approval conflict replaces the view", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill("conflict please");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("awaiting_approval").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText("This request cannot accept that decision.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByText("rejected").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
```

- [ ] **Step 2: Run test to verify it fails**

This step runs after Tasks 1–9 are implemented, so the headings exist and the spec should pass. Run it as the acceptance check, not as a red test against old markup.

Run from `ui/`: `npx playwright test`

Expected before Tasks 3, 6, 7, and 8: FAIL looking for `New request` or `Request review`. After those tasks: PASS, 2 tests.

- [ ] **Step 3: Write minimal implementation**

No production change in this task. The assertions match markup from Tasks 3, 6, 7, 8, and 9. If a locator fails, fix the assertion only when the accessible name drifted from this plan. Do not change the fake server.

- [ ] **Step 4: Run test to verify it passes**

Run from `ui/`: `npx playwright test`

Expected: 2 passed. If Chromium is missing, install the Playwright browser that `ui/package.json` already depends on. Do not add a package.

- [ ] **Step 5: Commit**

```bash
git add ui/e2e/approve.spec.ts ui/e2e/conflict.spec.ts
git commit -m "$(cat <<'EOF'
test(ui): assert the review surface in the browser

EOF
)"
```

### Task 11: Documentation sentences

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/roadmap.md`
- Do not modify: `tests/unit/docs/test_operator_ui_docs.py`

**Interfaces:**
- Consumes: locked sentences that the docs test already requires
- Produces: additive sentences only

- [ ] **Step 1: Write the failing test**

Do not add a Python test. The existing test must keep passing unchanged. The acceptance check is that these strings exist after the edit:

- `The operator UI does not add authentication.`
- `The operator UI does not make this API safe for public Internet exposure.`
- `Batch 31 — operator UI (complete)`
- `Batch 32 presents that same public request DTO.`
- `Batch 32 — operator UI presentation (complete)`

- [ ] **Step 2: Run test to verify it fails**

Run from the repository root:

```bash
.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q
```

Expected: PASS before the edit. This task does not have a red Python test. The new sentences are absent until Step 3. Confirm absence with:

```bash
grep -n "Batch 32 presents that same public request DTO" docs/api.md || echo ABSENT
```

Expected: `ABSENT`

- [ ] **Step 3: Write minimal implementation**

In `docs/api.md`, immediately after the paragraph that begins `The UI renders the public request DTO only.`, add this paragraph:

```markdown
Batch 32 presents that same public request DTO. It does not add a route, a field, or a workflow state. Server status values stay visible. A destructive plan is still the server boolean, and the page still says "Destructive change detected."
```

Do not edit the sentences the docs test locks.

In `docs/roadmap.md`, after the Batch 31 section and before `## Not yet started`, add:

```markdown
## Batch 32 — operator UI presentation (complete)

The operator UI is a review surface over the public request DTO. Labels may
sit beside server enums. The enums stay visible. The batch does not add
authentication, request history, or a new API. The design is
`docs/superpowers/specs/2026-09-28-batch32-design.md`. The plan is
`docs/superpowers/plans/2026-09-28-batch32-operator-ui-presentation.md`.
```

- [ ] **Step 4: Run test to verify it passes**

Run from the repository root:

```bash
.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q
```

Expected: PASS without editing the test file. If this test fails, stop. Do not change production Python to make a wording edit pass.

- [ ] **Step 5: Commit**

```bash
git add docs/api.md docs/roadmap.md
git commit -m "$(cat <<'EOF'
docs: describe the operator review surface

EOF
)"
```

### Task 12: Frontend and Python regression

**Files:**
- No planned production edits.

**Interfaces:**
- Consumes: the commits from Tasks 1–11
- Produces: a recorded pass of the command list below, or a stop if a command fails

- [ ] **Step 1: Run the frontend checks**

From `ui/`:

```bash
npm test
npm run build
npx playwright test
```

Expected: Vitest passes, `tsc --noEmit` inside the build passes, Vite build passes, Playwright passes 2 tests.

- [ ] **Step 2: Run the Python and whitespace checks**

From the repository root:

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: pytest passes. Ruff passes. `git diff --check` prints nothing.

Do not rerun Docker image tests unless a command above shows a packaged-runtime file changed. CSS and React source are compiled into the image only on a later image build. This batch must not change that build.

- [ ] **Step 3: Confirm the diff boundary**

```bash
git diff --name-only d177047e5dcab785bbe4c7a8e4203759e960a629...HEAD
```

Expected names stay inside `ui/`, `docs/api.md`, `docs/roadmap.md`, and the Batch 32 design and plan docs. If `src/iac_agent/`, `Dockerfile`, `compose.yaml`, or `.github/` appears, stop and report it. Do not add a follow-up commit that broadens the batch.

- [ ] **Step 4: Commit**

No commit if the checks pass and the tree is clean. If a check fails, fix it inside the task that owns the file and make a new commit. Do not amend a pushed commit. This plan is not pushed during implementation unless a later human instruction says to push.

---

## Self-review

Spec coverage:

- Shell, hierarchy, composer, open request, health, summary, workflow, plan counts, findings, approval, dialog, polling, errors, pull-request URL, narrow layout, focus, and tokens are Tasks 1–10.
- Approved decisions are Global Constraints: presentation-only, no DTO field, raw enums visible, no component library, no history or auth, destructive sentence preserved.
- Non-goals are the "do not modify" file list and the stop condition for Python, Docker, and CI.
- Security tests already in `projection.test.tsx` stay in place. Playwright still asserts the hidden ARN, message, and address are absent.

Placeholder scan: no task defers behavior to a later unnamed change. Task 10 has no production code because the markup arrives in earlier tasks. Task 12 is the regression gate, not a feature.

Type consistency: `enumCaption` and `AuthoritativeValue` are created in Task 4 and used by Tasks 4 and 5. `CONFIRM_TEXT` is not renamed. Button names match the existing tests.

## Design conflict

None. Inspection of `tests/docker/test_ui_runtime.py` and `tests/unit/api/test_ui_static.py` shows they only require the string `IaC Agent Platform` in `index.html`. This plan keeps that title and the `h1`. `tests/unit/docs/test_operator_ui_docs.py` checks inclusion of existing sentences. Task 11 adds sentences and does not remove those sentences, and it does not edit the test.

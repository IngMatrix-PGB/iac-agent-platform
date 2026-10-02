# Batch 36 Operator UI Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present the existing operator UI as an infrastructure control plane: one status label, a product shell, a scannable catalog, and a review page that leads with the resource, the security gate, the plan, and the human decision.

**Architecture:** Stay on the current React 19 client, the two routes in `ui/src/router.ts`, and `ApiClient`. Add a status-label module and CSS tokens. Pages keep rendering the current DTOs. `project_view` stays name-only on reload, and the review page omits fields that are null. No new route, store, or dependency.

**Tech Stack:** React 19, Vite, Vitest, Testing Library, Playwright. One global stylesheet, `ui/src/styles.css`. No component library.

**Design:** `docs/superpowers/specs/2026-10-01-batch36-ui-ux-productization-design.md`

## Global Constraints

- Display heading is `IaC Agent`. The line under it is `Infrastructure control plane`. Do not rename the repository. Do not change the document title in `ui/index.html`; `tests/docker/test_ui_runtime.py` asserts the built HTML contains `IaC Agent Platform`.
- Routes stay `/` and `/requests/{request_id}`. Unknown paths still render `Page not found.` Do not add a router package.
- The operator secret stays in React state. Reload clears it. No `localStorage`, `sessionStorage`, cookie, or `VITE_` name.
- Runtime copy is only `Runtime ready`, `Runtime not ready`, or `Runtime unreachable`. It must not mention GitHub, OpenAI, or capability configuration.
- Human labels, exactly: `pass` Pass, `warn` Warn, `block` Block, `awaiting_approval` Awaiting approval, `pending` Pending, `running` Running, `approved` Approved, `rejected` Rejected, `blocked` Blocked, `error` Error, `pr_created` Pull request created. Stage and severity use the same function. Unknown values keep the current first-letter caption (`enumCaption`) and are not given a new word.
- The raw enum is the `title` attribute. It is not a second visible text node.
- Pass, Warn, and Block each have their own token pair. Pull request created does not use the pass tokens. Workflow error does not use the block tokens.
- `Warnings still go to human review.` only when `security_status` is `warn` and `approval_available` is true.
- `Approval is closed.` when `security_status` is `block` or `workflow_status` is `blocked`. `ApprovalPanel` still returns null unless `approval_available` is true.
- Approve still opens the dialog. The dialog sentence stays `Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.` Cancel keeps initial focus. Reject still calls `decide` immediately.
- Persistent no-apply sentence stays `Terraform apply was not executed.`
- Capability message strings stay the server `message` verbatim. `This request was not saved.` stays for interpreter failures (HTTP 502, 503, 504).
- `request_exists` uses the conflict border and the message `Request already exists.` It does not render the heading `Approval conflict`.
- `approval_conflict` uses the conflict border, the heading `Approval conflict`, and the message `This request cannot accept that decision.` The embedded `request` still replaces the view.
- Validation and network failures use the error border and the existing message. They do not render the heading `Workflow error`.
- A durable workflow `error` renders the heading `Workflow error`, then stage and error type once each.
- Loading copy stays `Loading request.` Polling copy stays `Checking this request.`
- Empty catalog copy becomes `No indexed requests. A checkpoint created before the durable index can still be opened by request id.`
- Do not render `Unavailable after reload.`
- Do not show raw Terraform plan JSON, finding `resource`, finding `message`, or workflow error `message`.
- Plan heading stays `Terraform plan summary`. Counts stay Add, Change, Destroy. The destructive sentence stays tied to `destructive_change_detected`.
- Findings caption stays `Security findings`. Below `40rem`, a stacked list replaces the table visually. Both structures exist in the DOM; CSS decides which is shown.
- Do not add a dependency. Do not edit `package.json` or lockfiles.
- Do not edit `src/iac_agent/`, `tests/` outside `ui/`, `terraform/`, `docs/api.md`, `docs/roadmap.md`, or the approved design spec.
- No Terraform apply or destroy. No live provider tests. No `real_llm` evals.
- Create commits with `git commit-tree` and `git reset --soft`, author and committer `IngMatrix-PGB <167713460+IngMatrix-PGB@users.noreply.github.com>`. Do not amend. Run `scripts/check_commit_attribution.py` on the message file before `commit-tree`. The message must not contain `Co-Authored-By`, `Generated-By`, `Made with Cursor`, `Claude`, or `Anthropic`.
- If a task's new test passes before the production edit, the production file for that assertion is already correct. Do not change it. Continue with the collateral test updates that the rest of the task names.
- If the 1440×900 assertion in Task 11 fails, stop. Do not shrink the type scale, hide findings, delete the no-apply sentence, or change the fixture to make it pass.

## File map

- Create `ui/src/components/status-label.ts`: `statusLabel` and `chipClass`.
- Create `ui/src/components/status-label.test.ts`.
- Modify `ui/src/styles.css`: tokens, type, chips, buttons, notices, catalog row, finding stack.
- Modify `ui/src/components/authoritative-value.tsx`: one visible label, `title` holds the enum.
- Modify `ui/src/components/findings.tsx`: labels in the table and a stacked list.
- Modify `ui/src/components/error-banner.tsx`: `tone` and `noticeTone`.
- Modify `ui/src/components/health-indicator.tsx`: three runtime sentences.
- Modify `ui/src/app.tsx`: shell, nav landmark, auth copy, focus target.
- Modify `ui/src/pages/compose-page.tsx`: catalog rows, empty copy, notice tones.
- Modify `ui/src/pages/request-page.tsx`: hierarchy order, back link, notice tones.
- Modify `ui/src/components/request-summary.tsx`: name leads; omit null intent and architecture.
- Modify `ui/src/components/workflow-status.tsx`: chips, stage once, warn/block sentences, PR link, workflow-error heading.
- Modify `ui/src/components/approval-panel.tsx`: primary and secondary buttons.
- Modify `ui/src/components/plan-summary.tsx`: no behavior change beyond existing classes.
- Modify `ui/src/components/request-form.tsx` and `ui/src/components/open-request.tsx`: button classes only.
- Modify the unit tests listed in each task, plus `ui/e2e/approve.spec.ts`, `ui/e2e/conflict.spec.ts`, `ui/e2e/recent-requests.spec.ts`.
- Create `ui/e2e/portfolio.spec.ts`.
- Do not modify `ui/src/api/client.ts`, `ui/src/api/types.ts`, `ui/src/api/polling.ts`, or `ui/src/router.ts`.

## Gate split

Gate A adds the label primitive and tokens. Pages still have today's section order. Gate B adds the shell. Gate C changes the catalog and compose notices. Gate D reorders the review page. Gate E adds the trust sentences and button roles. Gate F finishes error headings and the narrow findings list. Gate G is the Playwright portfolio spec. Gate H runs the suites and does not add a feature.

---

## Gate A — design system and status primitives

### Task 1: Status labels

**Files:**
- Create: `ui/src/components/status-label.ts`
- Test: `ui/src/components/status-label.test.ts`

**Interfaces:**
- Produces: `statusLabel(value: string): string`, `chipClass(value: string): string`, `enumCaption(value: string): string`
- Consumes: nothing

- [ ] **Step 1: Write the failing test**

Create `ui/src/components/status-label.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { chipClass, enumCaption, statusLabel } from "./status-label";

describe("statusLabel", () => {
  it("maps the design labels once", () => {
    expect(statusLabel("pass")).toBe("Pass");
    expect(statusLabel("warn")).toBe("Warn");
    expect(statusLabel("block")).toBe("Block");
    expect(statusLabel("awaiting_approval")).toBe("Awaiting approval");
    expect(statusLabel("pr_created")).toBe("Pull request created");
    expect(statusLabel("blocked")).toBe("Blocked");
    expect(statusLabel("error")).toBe("Error");
    expect(statusLabel("rejected")).toBe("Rejected");
    expect(statusLabel("pending")).toBe("Pending");
    expect(statusLabel("running")).toBe("Running");
    expect(statusLabel("approved")).toBe("Approved");
    expect(statusLabel("security_gate")).toBe("Security gate");
    expect(statusLabel("plan_analysis")).toBe("Plan analysis");
    expect(statusLabel("source_control")).toBe("Source control");
    expect(statusLabel("high")).toBe("High");
    expect(statusLabel("critical")).toBe("Critical");
  });

  it("does not invent a word for an unknown enum", () => {
    expect(enumCaption("custom_stage")).toBe("Custom stage");
    expect(statusLabel("custom_stage")).toBe("Custom stage");
  });

  it("assigns distinct chip classes to pass, warn, and block", () => {
    expect(chipClass("pass")).toBe("chip chip-pass");
    expect(chipClass("warn")).toBe("chip chip-warn");
    expect(chipClass("block")).toBe("chip chip-block");
    expect(chipClass("blocked")).toBe("chip chip-block");
    expect(chipClass("awaiting_approval")).toBe("chip chip-attention");
    expect(chipClass("pr_created")).toBe("chip chip-published");
    expect(chipClass("rejected")).toBe("chip chip-rejected");
    expect(chipClass("pending")).toBe("chip chip-neutral");
    expect(chipClass("running")).toBe("chip chip-neutral");
    expect(chipClass("approved")).toBe("chip chip-neutral");
    expect(chipClass("error")).toBe("chip chip-error");
    expect(chipClass("custom_stage")).toBe("chip");
    expect(chipClass("pass")).not.toBe(chipClass("warn"));
    expect(chipClass("warn")).not.toBe(chipClass("block"));
    expect(chipClass("pr_created")).not.toBe(chipClass("pass"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/status-label.test.ts`

Expected: FAIL because `./status-label` cannot be resolved.

- [ ] **Step 3: Write minimal implementation**

Create `ui/src/components/status-label.ts`:

```ts
const LABELS: Record<string, string> = {
  pass: "Pass",
  warn: "Warn",
  block: "Block",
  awaiting_approval: "Awaiting approval",
  pending: "Pending",
  running: "Running",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked",
  error: "Error",
  pr_created: "Pull request created",
  render: "Render",
  terraform: "Terraform",
  terraform_plan: "Terraform plan",
  plan_analysis: "Plan analysis",
  platform_policy: "Platform policy",
  checkov: "Checkov",
  security_gate: "Security gate",
  approval: "Approval",
  source_control: "Source control",
  complete: "Complete",
  publish: "Publish",
  high: "High",
  medium: "Medium",
  low: "Low",
  critical: "Critical",
};

const CHIP: Record<string, string> = {
  pass: "chip chip-pass",
  warn: "chip chip-warn",
  block: "chip chip-block",
  blocked: "chip chip-block",
  awaiting_approval: "chip chip-attention",
  pr_created: "chip chip-published",
  pending: "chip chip-neutral",
  running: "chip chip-neutral",
  approved: "chip chip-neutral",
  rejected: "chip chip-rejected",
  error: "chip chip-error",
};

export function enumCaption(value: string): string {
  const spaced = value.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function statusLabel(value: string): string {
  return LABELS[value] ?? enumCaption(value);
}

export function chipClass(value: string): string {
  return CHIP[value] ?? "chip";
}
```

`publish` and `terraform_plan` are in the map because the browser fake and the polling fixture use those stage strings. They are display labels for existing stage values, not new workflow statuses.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/components/status-label.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit only `ui/src/components/status-label.ts` and `ui/src/components/status-label.test.ts`.

```
feat: name each operator status once

Later screens need one human label per server enum, with the raw value kept off the caption line.
```

**Invariant:** No page, API client, or backend file changes. Backend enum strings are not renamed.

### Task 2: Tokens, chips, and buttons

**Files:**
- Modify: `ui/src/styles.css`
- Test: `ui/src/styles.test.ts`

**Interfaces:**
- Produces: the CSS class names and custom properties listed in the test
- Consumes: nothing from Task 1 yet

- [ ] **Step 1: Write the failing test**

Create `ui/src/styles.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "styles.css"), "utf8");

describe("operator design tokens", () => {
  it("defines distinct text-plus-surface pairs for the status roles", () => {
    for (const name of [
      "--color-status-pass-text",
      "--color-status-pass-surface",
      "--color-status-warn-text",
      "--color-status-warn-surface",
      "--color-status-block-text",
      "--color-status-block-surface",
      "--color-status-attention-text",
      "--color-status-attention-surface",
      "--color-status-published-text",
      "--color-status-published-surface",
      "--color-status-neutral-text",
      "--color-status-neutral-surface",
      "--color-status-rejected-text",
      "--color-status-rejected-surface",
      "--color-notice-config-text",
      "--color-notice-config-border",
      "--color-notice-error-text",
      "--color-notice-error-border",
      "--color-notice-conflict-text",
      "--color-notice-conflict-border",
      "--color-notice-missing-text",
      "--color-notice-missing-border",
    ]) {
      expect(css).toContain(name);
    }
    expect(css).toContain(".chip-pass");
    expect(css).toContain(".chip-warn");
    expect(css).toContain(".chip-block");
    expect(css).toContain(".chip-attention");
    expect(css).toContain(".chip-published");
    expect(css).toContain(".chip-neutral");
    expect(css).toContain(".chip-rejected");
    expect(css).toContain(".chip-error");
    expect(css).toContain(".button-primary");
    expect(css).toContain(".button-secondary");
    expect(css).toContain(".notice-config");
    expect(css).toContain(".notice-error");
    expect(css).toContain(".notice-conflict");
    expect(css).toContain(".notice-missing");
    expect(css).toContain(".finding-stack");
    expect(css).toContain("@media (max-width: 40rem)");
  });

  it("does not reuse the pass surface for publication or the block surface for workflow error", () => {
    const block = css.slice(css.indexOf(".chip-block"), css.indexOf(".chip-attention"));
    const published = css.slice(css.indexOf(".chip-published"), css.indexOf(".chip-neutral"));
    const error = css.slice(css.indexOf(".chip-error"), css.indexOf(".chip-error") + 240);
    expect(block).toContain("var(--color-status-block-surface)");
    expect(published).toContain("var(--color-status-published-surface)");
    expect(published).not.toContain("var(--color-status-pass-surface)");
    expect(error).toContain("var(--color-notice-error-border)");
    expect(error).not.toContain("var(--color-status-block-surface)");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/styles.test.ts`

Expected: FAIL because the new custom properties are absent.

- [ ] **Step 3: Write minimal implementation**

Append to `ui/src/styles.css` inside `:root`, after `--color-danger-border`:

```css
  --color-status-pass-text: #14532d;
  --color-status-pass-surface: #dcfce7;
  --color-status-warn-text: #78350f;
  --color-status-warn-surface: #fef3c7;
  --color-status-block-text: #7f1d1d;
  --color-status-block-surface: #fee2e2;
  --color-status-attention-text: #1e3a8a;
  --color-status-attention-surface: #dbeafe;
  --color-status-published-text: #312e81;
  --color-status-published-surface: #e0e7ff;
  --color-status-neutral-text: #44403c;
  --color-status-neutral-surface: #f5f5f4;
  --color-status-rejected-text: #292524;
  --color-status-rejected-surface: #e7e5e4;
  --color-notice-config-text: #78350f;
  --color-notice-config-border: #d97706;
  --color-notice-error-text: #1c1917;
  --color-notice-error-border: #44403c;
  --color-notice-conflict-text: #1e3a8a;
  --color-notice-conflict-border: #1d4ed8;
  --color-notice-missing-text: #44403c;
  --color-notice-missing-border: #a8a29e;
```

Append at the end of the file:

```css
.product-kicker {
  margin: 0 0 var(--space-3);
  color: var(--color-muted);
}

.meta {
  margin: 0 0 var(--space-3);
  color: var(--color-muted);
  font-family: var(--font-mono);
  font-size: 0.875rem;
}

.chip {
  display: inline-block;
  margin: 0 var(--space-2) var(--space-2) 0;
  padding: 0.1rem 0.4rem;
  border: 1px solid transparent;
  font-weight: 650;
}

.chip-pass {
  color: var(--color-status-pass-text);
  background: var(--color-status-pass-surface);
}

.chip-warn {
  color: var(--color-status-warn-text);
  background: var(--color-status-warn-surface);
}

.chip-block {
  color: var(--color-status-block-text);
  background: var(--color-status-block-surface);
}

.chip-attention {
  color: var(--color-status-attention-text);
  background: var(--color-status-attention-surface);
}

.chip-published {
  color: var(--color-status-published-text);
  background: var(--color-status-published-surface);
}

.chip-neutral {
  color: var(--color-status-neutral-text);
  background: var(--color-status-neutral-surface);
}

.chip-rejected {
  color: var(--color-status-rejected-text);
  background: var(--color-status-rejected-surface);
  border-color: var(--color-status-rejected-text);
}

.chip-error {
  color: var(--color-notice-error-text);
  background: var(--color-panel);
  border-color: var(--color-notice-error-border);
}

.button-primary {
  border-color: var(--color-text);
  background: var(--color-text);
  color: var(--color-surface);
}

.button-secondary {
  border-color: var(--color-border);
  background: var(--color-panel);
  color: var(--color-text);
}

.notice-config,
.notice-error,
.notice-conflict,
.notice-missing {
  margin: var(--space-4) 0;
  padding: var(--space-3) var(--space-4);
  background: var(--color-panel);
}

.notice-config {
  border: 1px solid var(--color-notice-config-border);
  color: var(--color-notice-config-text);
}

.notice-error {
  border: 1px solid var(--color-notice-error-border);
  color: var(--color-notice-error-text);
}

.notice-conflict {
  border: 1px solid var(--color-notice-conflict-border);
  color: var(--color-notice-conflict-text);
}

.notice-missing {
  border: 1px solid var(--color-notice-missing-border);
  color: var(--color-notice-missing-text);
}

.shell-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: end;
  justify-content: space-between;
}

.shell-nav {
  display: flex;
  gap: var(--space-3);
}

.catalog-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
  align-items: baseline;
  justify-content: space-between;
}

.finding-stack {
  display: none;
  margin: 0;
  padding: 0;
  list-style: none;
}

.approval-actions {
  display: flex;
  flex-wrap: wrap;
}

@media (max-width: 40rem) {
  .shell-bar,
  .approval-actions {
    display: block;
  }

  .approval-actions button {
    display: block;
    width: 100%;
  }

  .findings-table {
    display: none;
  }

  .finding-stack {
    display: block;
  }
}
```

Keep the existing `:focus-visible` rule. Do not remove `.plan-counts`, `.visually-hidden`, or `dialog`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/styles.test.ts`

Expected: PASS. The slice assertions depend on the class blocks staying in the order `.chip-block`, `.chip-attention`, `.chip-published`, `.chip-neutral`, `.chip-error`.

- [ ] **Step 5: Commit**

Commit only `ui/src/styles.css` and `ui/src/styles.test.ts`.

```
feat: add operator status and notice tokens

Pass, warn, block, publication, and workflow error need separate colors before the pages use them.
```

**Invariant:** No component behavior changes. The light page background stays `--color-surface`.

### Task 3: One visible label

**Files:**
- Modify: `ui/src/components/authoritative-value.tsx`
- Modify: `ui/src/components/findings.tsx`
- Modify: `ui/src/components/authoritative-value.test.tsx`
- Modify: `ui/src/components/projection.test.tsx`
- Modify: `ui/src/pages/compose-page.test.tsx`
- Modify: `ui/src/app.test.tsx`
- Modify: `ui/src/pages/request-page.test.tsx`
- Modify: `ui/e2e/approve.spec.ts`
- Modify: `ui/e2e/conflict.spec.ts`
- Modify: `ui/e2e/recent-requests.spec.ts`

**Interfaces:**
- Consumes: `statusLabel`, `chipClass`, `enumCaption` from `ui/src/components/status-label.ts`
- Produces: `AuthoritativeValue` renders one visible label and `title={value}`

- [ ] **Step 1: Write the failing test**

Replace `ui/src/components/authoritative-value.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthoritativeValue } from "./authoritative-value";
import { enumCaption } from "./status-label";

describe("authoritative value", () => {
  it("shows the human label once and keeps the enum on the title", () => {
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="awaiting_approval" />
      </dl>,
    );
    const label = screen.getByText("Awaiting approval");
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(label).toHaveAttribute("title", "awaiting_approval");
    expect(label).toHaveClass("chip", "chip-attention");
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
  });

  it("uses the publication label rather than the mechanical caption", () => {
    expect(enumCaption("pr_created")).toBe("Pr created");
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="pr_created" />
      </dl>,
    );
    expect(screen.getByText("Pull request created")).toHaveAttribute("title", "pr_created");
    expect(screen.queryByText("pr_created")).not.toBeInTheDocument();
    expect(screen.queryByText("Pr created")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/authoritative-value.test.tsx`

Expected: FAIL because the raw enum is still visible and the import of `enumCaption` from `./status-label` may succeed while the component still renders both strings.

- [ ] **Step 3: Write minimal implementation**

Replace `ui/src/components/authoritative-value.tsx` with:

```tsx
import { chipClass, statusLabel } from "./status-label";

export { enumCaption, statusLabel } from "./status-label";

export function AuthoritativeValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt role="term" aria-label={label}>
        {label}
      </dt>
      <dd>
        <span className={chipClass(value)} title={value}>
          {statusLabel(value)}
        </span>
      </dd>
    </div>
  );
}
```

In `ui/src/components/findings.tsx`, import `chipClass` and `statusLabel`. Render status and severity as:

```tsx
<span className={chipClass(finding.status)} title={finding.status}>
  {statusLabel(finding.status)}
</span>
```

and the same for `finding.severity`. Keep `policy_id` in `<code className="enum">`. Keep the table, its caption, and the column headers. Add `className="findings-table"` on the `<table>`. After the table, render:

```tsx
<ul className="finding-stack">
  {findings.map((finding) => (
    <li key={`${finding.policy_id}:${finding.status}:${finding.severity}`}>
      <p>Policy</p>
      <p>
        <code className="enum">{finding.policy_id}</code>
      </p>
      <p>Status</p>
      <p>
        <span className={chipClass(finding.status)} title={finding.status}>
          {statusLabel(finding.status)}
        </span>
      </p>
      <p>Severity</p>
      <p>
        <span className="chip" title={finding.severity}>
          {statusLabel(finding.severity)}
        </span>
      </p>
    </li>
  ))}
</ul>
```

The stack is in the DOM in Gate A and hidden by the CSS from Task 2 until the viewport is narrow. Do not remove the table.

Update assertions that require the raw enum as visible text. The human label replaces it. Keep assertions that the raw enum is absent when it was already a negative assertion.

In `ui/src/components/projection.test.tsx`:

- `getAllByText("awaiting_approval")` becomes `getAllByText("Awaiting approval")`, and add `expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument()`.
- `getByText("approval")` becomes `getByRole` or `getByText("Approval", { exact: true })` so it does not match the still-present sentence `Approval available`.
- `getAllByText("warn")` becomes `getAllByText("Warn")`, and `queryByText("warn")` is not in the document.
- `getByText("terraform")` becomes `getAllByText("Terraform")`.
- `getAllByText("RuntimeError")` stays, because that error type is not in the label map and its caption is `RuntimeError`.

In `ui/src/pages/compose-page.test.tsx`, `ui/src/app.test.tsx`, and `ui/src/pages/request-page.test.tsx`, replace visible raw enums the same way: `awaiting_approval` to `Awaiting approval`, `pass` to `Pass`, `pr_created` to `Pull request created`, `rejected` to `Rejected`. Leave `queryByText("pending")` and `queryByText("null")` as negative assertions.

In the three Playwright specs, replace visible positive lookups:

- `awaiting_approval` with `Awaiting approval`
- `pass` with `Pass` where the locator is the security chip (`getByText("pass")`)
- `pr_created` with `Pull request created`
- `rejected` with `Rejected`

Leave `toHaveCount(0)` assertions on the raw enums. They should still pass.

Do not change page layout, headings, or `Approval available` in this task. Those strings stay until later gates.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS. Playwright is not required in this gate.

- [ ] **Step 5: Commit**

Commit the files listed for this task.

```
feat: stop printing a status beside its own enum

The caption already says the state. The server value stays available as the title.
```

**Invariant:** `ui/src/api/types.ts` is unchanged. Findings still omit `resource` and `message`.

---

## Gate B — product shell and authentication

### Task 4: Shell, runtime mark, and auth copy

**Files:**
- Modify: `ui/src/app.tsx`
- Modify: `ui/src/components/health-indicator.tsx`
- Modify: `ui/src/app.test.tsx`
- Modify: `ui/e2e/approve.spec.ts`
- Modify: `ui/e2e/recent-requests.spec.ts`

**Interfaces:**
- Consumes: existing `parseRoute`, `HealthIndicator`, `ComposePage`, `RequestPage`
- Produces: nav landmark `Primary`; runtime text `Runtime ready` | `Runtime not ready` | `Runtime unreachable`; auth sentence `This secret stays in this tab's memory. Reloading the page clears it.`

- [ ] **Step 1: Write the failing test**

Add these tests to the `operator shell` describe in `ui/src/app.test.tsx`:

```tsx
it("names the product and offers Compose and Requests", async () => {
  const user = userEvent.setup();
  render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
  expect(screen.getByRole("heading", { level: 1, name: "IaC Agent" })).toBeInTheDocument();
  expect(screen.getByText("Infrastructure control plane")).toBeInTheDocument();
  expect(screen.queryByText("Local operator console. Review the server response before approving a request.")).not.toBeInTheDocument();
  const nav = screen.getByRole("navigation", { name: "Primary" });
  expect(nav).toBeInTheDocument();
  await continueAsOperator(user);
  expect(screen.getByRole("link", { name: "Compose" })).toHaveAttribute("href", "/#compose");
  expect(screen.getByRole("link", { name: "Requests" })).toHaveAttribute("href", "/#requests");
});

it("describes runtime readiness without naming providers", async () => {
  render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
  expect(await screen.findByText("Runtime ready")).toBeInTheDocument();
  expect(screen.queryByText(/GitHub|OpenAI|capability/i)).not.toBeInTheDocument();
  expect(screen.queryByText("API process responded.")).not.toBeInTheDocument();
  expect(screen.queryByText("Application process is ready to accept requests.")).not.toBeInTheDocument();
});

it("says the secret stays in tab memory and does not write storage", async () => {
  const user = userEvent.setup();
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
  expect(
    screen.getByText("This secret stays in this tab's memory. Reloading the page clears it."),
  ).toBeInTheDocument();
  await continueAsOperator(user);
  expect(setItem).not.toHaveBeenCalled();
  expect(document.cookie).toBe("");
  setItem.mockRestore();
});

it("asks for the secret again on a fresh mount", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
  await continueAsOperator(user);
  expect(screen.queryByLabelText("Operator secret")).not.toBeInTheDocument();
  unmount();
  render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
  expect(screen.getByLabelText("Operator secret")).toHaveValue("");
});
```

Update the existing unknown-route and health tests in that file so they expect heading `IaC Agent` and `Runtime ready`, and they no longer expect `IaC Agent Platform` or the two old health sentences.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/app.test.tsx`

Expected: FAIL because the heading is still `IaC Agent Platform` and the runtime sentences are the old pair.

- [ ] **Step 3: Write minimal implementation**

Replace the header and secret form in `ui/src/app.tsx`. Keep `secret` in `useState<string | null>(null)`.

```tsx
const [focusId, setFocusId] = useState<"compose" | "requests" | null>(null);

function openRegion(id: "compose" | "requests") {
  if (route.name !== "compose") {
    navigate("/");
  }
  setFocusId(id);
}

useEffect(() => {
  if (focusId === null || operatorClient === null) {
    return;
  }
  document.getElementById(focusId)?.focus();
  setFocusId(null);
}, [focusId, operatorClient, route.name]);
```

Header:

```tsx
<header className="shell-header">
  <div className="shell-bar">
    <div>
      <h1>IaC Agent</h1>
      <p className="product-kicker">Infrastructure control plane</p>
    </div>
    <nav className="shell-nav" aria-label="Primary">
      <a
        href="/#compose"
        onClick={(event) => {
          event.preventDefault();
          openRegion("compose");
        }}
      >
        Compose
      </a>
      <a
        href="/#requests"
        onClick={(event) => {
          event.preventDefault();
          openRegion("requests");
        }}
      >
        Requests
      </a>
    </nav>
  </div>
  <HealthIndicator client={client} />
</header>
```

Secret copy, replacing the current paragraph:

```tsx
<p>This secret stays in this tab's memory. Reloading the page clears it.</p>
```

Add `className="button-primary"` to Continue.

`HealthIndicator` returns one sentence inside the existing `section aria-label="Process status"`:

| health | ready | text |
|---|---|---|
| success `ok` | success `ready` | Runtime ready |
| success `ok` | anything else | Runtime not ready |
| anything else | ignored | Runtime unreachable |

Remove the definition list. Do not read `capabilities`.

Give the compose section `id="compose"` and `tabIndex={-1}` in `compose-page.tsx` only if Task 4's focus test needs it. The focus test above does not click the nav. Add one test that clicks Requests while `pathname` is `/requests/req-1` and expects `navigate` to have been called with `"/"`. The section ids are added in Task 5; until then `getElementById` may return null and the effect still clears `focusId`.

Update Playwright headings from `IaC Agent Platform` to `IaC Agent` in `ui/e2e/approve.spec.ts` and `ui/e2e/recent-requests.spec.ts`. Leave `ui/index.html` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS.

- [ ] **Step 5: Commit**

```
feat: give the operator UI a control-plane shell

The runtime mark reports process readiness only, and the operator secret stays in memory.
```

**Invariant:** `createOperatorClient` in `ui/src/main.tsx` is unchanged. A 401 still calls `clearSecret`. `ui/src/router.ts` is unchanged.

---

## Gate C — composer and request catalog

### Task 5: Scannable catalog rows

**Files:**
- Modify: `ui/src/pages/compose-page.tsx`
- Modify: `ui/src/components/request-form.tsx`
- Modify: `ui/src/components/open-request.tsx`
- Modify: `ui/src/pages/compose-page.test.tsx`
- Modify: `ui/src/app.test.tsx`
- Modify: `ui/e2e/recent-requests.spec.ts`

**Interfaces:**
- Consumes: `statusLabel`, `chipClass`
- Produces: catalog link accessible name is the resource name when `name` is non-null, otherwise the request id

- [ ] **Step 1: Write the failing test**

In `ui/src/pages/compose-page.test.tsx`, change the listed-row assertions to:

```tsx
const EMPTY_COPY =
  "No indexed requests. A checkpoint created before the durable index can still be opened by request id.";

expect(await screen.findByRole("link", { name: "orders" })).toHaveAttribute(
  "href",
  "/requests/req-listed",
);
expect(screen.getByText("req-listed").className).toContain("meta");
expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
expect(screen.getByText("Pass")).toBeInTheDocument();
expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
expect(screen.queryByText("Approval not available")).not.toBeInTheDocument();
expect(screen.queryByText("2026-09-29T00:00:02.000000Z")).not.toBeInTheDocument();
expect(screen.getByRole("link", { name: "orders" }).closest("li")).toHaveAttribute(
  "title",
  "2026-09-29T00:00:02.000000Z",
);
expect(screen.getByRole("link", { name: "req/a b" })).toBeInTheDocument();
expect(screen.getByText("Pull request created")).toBeInTheDocument();
expect(screen.queryByText("Security status")).not.toBeInTheDocument();
```

The null-name row still must not render the sentinels in `HIDDEN`. The open-request button has class `button-secondary`. Submit has class `button-primary`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/pages/compose-page.test.tsx`

Expected: FAIL because the link name is still `req-listed` and the empty copy is the old paragraph.

- [ ] **Step 3: Write minimal implementation**

In `RecentRequests`, replace `EMPTY_INDEX` with the new `EMPTY_COPY`. For each row:

```tsx
<li className="panel catalog-row" key={row.request_id} title={row.created_at}>
  <div>
    <a
      href={path}
      onClick={(event) => {
        event.preventDefault();
        navigate(path);
      }}
    >
      {row.name ?? row.request_id}
    </a>
    {row.name ? <p className="meta">{row.request_id}</p> : null}
  </div>
  <div>
    <span className={chipClass(row.workflow_status)} title={row.workflow_status}>
      {statusLabel(row.workflow_status)}
    </span>
    {row.security_status ? (
      <span className={chipClass(row.security_status)} title={row.security_status}>
        {statusLabel(row.security_status)}
      </span>
    ) : null}
  </div>
</li>
```

Do not render `Approval available`. Put `id="compose"` and `tabIndex={-1}` on the compose `<section>`. Put `id="requests"` and `tabIndex={-1}` on the recent-requests `<section>`.

`RequestForm` submit button: `className="button-primary"`. `OpenRequest` button: `className="button-secondary"`. The open-request heading stays `Open a saved request`.

Update `ui/src/app.test.tsx` catalog expectations the same way. Update `ui/e2e/recent-requests.spec.ts` so the visible row is link `orders`, chip `Awaiting approval`, chip `Pass`, and it does not require the timestamp or `Approval available` to be visible. Keep the sentinel `toHaveCount(0)` checks. The direct visit to `/requests/req-indexed` still shows `orders`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/pages/compose-page.test.tsx src/app.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```
feat: lead the request catalog with the resource name

Operators need to see which change is waiting without reading a definition list.
```

**Invariant:** `listRequests()` is still called once. Navigation still uses `navigate(\`/requests/${encodeURIComponent(id)}\`)`. No search or sort is added.

### Task 6: Compose notices

**Files:**
- Modify: `ui/src/components/error-banner.tsx`
- Create: `ui/src/components/error-banner.test.tsx`
- Modify: `ui/src/pages/compose-page.tsx`
- Modify: `ui/src/app.test.tsx`

**Interfaces:**
- Produces: `noticeTone(error: string): "config" | "error" | "conflict" | "missing"` and `ErrorBanner` props `{ message: string; tone: NoticeTone }`

- [ ] **Step 1: Write the failing test**

Create `ui/src/components/error-banner.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorBanner, noticeTone } from "./error-banner";

const INTENT =
  "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY.";

describe("noticeTone", () => {
  it("separates configuration, conflict, missing, and other failures", () => {
    expect(noticeTone("capability_unavailable")).toBe("config");
    expect(noticeTone("approval_conflict")).toBe("conflict");
    expect(noticeTone("request_exists")).toBe("conflict");
    expect(noticeTone("request_not_found")).toBe("missing");
    expect(noticeTone("internal_error")).toBe("error");
    expect(noticeTone("invalid_request")).toBe("error");
    expect(noticeTone("network")).toBe("error");
  });
});

describe("ErrorBanner", () => {
  it("heads a missing capability without calling it a workflow error", () => {
    render(<ErrorBanner message={INTENT} tone="config" />);
    expect(screen.getByRole("heading", { name: "Not configured" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(INTENT);
    expect(screen.getByRole("alert")).toHaveClass("notice-config");
    expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
  });

  it("heads an approval conflict and leaves a duplicate create untitled", () => {
    render(
      <ErrorBanner message="This request cannot accept that decision." tone="conflict" />,
    );
    expect(screen.getByRole("heading", { name: "Approval conflict" })).toBeInTheDocument();
    render(<ErrorBanner message="Request already exists." tone="conflict" />);
    expect(screen.getAllByRole("heading", { name: "Approval conflict" })).toHaveLength(1);
    expect(screen.getByText("Request already exists.")).toBeInTheDocument();
  });

  it("shows a network failure without a workflow-error heading", () => {
    render(<ErrorBanner message="The API could not be reached." tone="error" />);
    expect(screen.getByRole("alert")).toHaveClass("notice-error");
    expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/error-banner.test.tsx`

Expected: FAIL because `noticeTone` is not exported and `ErrorBanner` does not take `tone`.

- [ ] **Step 3: Write minimal implementation**

```tsx
import { useEffect, useRef } from "react";

export type NoticeTone = "config" | "error" | "conflict" | "missing";

export function noticeTone(error: string): NoticeTone {
  if (error === "capability_unavailable") {
    return "config";
  }
  if (error === "approval_conflict" || error === "request_exists") {
    return "conflict";
  }
  if (error === "request_not_found") {
    return "missing";
  }
  return "error";
}

const HEADING: Record<NoticeTone, string | null> = {
  config: "Not configured",
  error: null,
  conflict: null,
  missing: null,
};

export function ErrorBanner({ message, tone }: { message: string; tone: NoticeTone }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [message]);
  const heading = tone === "conflict" && message === "This request cannot accept that decision."
    ? "Approval conflict"
    : HEADING[tone];
  return (
    <div className={`notice-${tone}`} role="alert" tabIndex={-1} ref={ref}>
      {heading ? <h3>{heading}</h3> : null}
      <p>{message}</p>
    </div>
  );
}
```

In `compose-page.tsx`, store `{ message, tone }` instead of a string. On `result.kind === "http"`, `tone` is `noticeTone(result.error)`. On `result.kind === "network"`, `tone` is `"error"`. Keep `setUnsaved(result.kind === "http" && isInterpreterFailure(result.status))`. Pass `tone` into `ErrorBanner`.

Extend the existing unsaved-result test in `ui/src/app.test.tsx` that submits and receives HTTP 503 `capability_unavailable`: expect heading `Not configured`, the verbatim intent message, class `notice-config`, and `This request was not saved.` Add a sibling case for `request_exists` / `Request already exists.` that expects `notice-conflict` and zero `Approval conflict` headings.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS. Every existing `<ErrorBanner message=...>` call must be updated to pass `tone` or the typecheck fails. Request-page banners can pass `noticeTone(result.error)` in this task so the suite typechecks; the request-page behavior tests are tightened in Task 9.

- [ ] **Step 5: Commit**

```
feat: separate a missing capability from a failed workflow

Submit already receives capability_unavailable. The composer should not present that as a run failure.
```

**Invariant:** Submit still posts `{ natural_language_request }`. HTTP 201 with a workflow still navigates. Clarification and unsupported stay on `/` in `Unsaved result`.

---

## Gate D — request review hierarchy

### Task 7: Resource-first review

**Files:**
- Modify: `ui/src/pages/request-page.tsx`
- Modify: `ui/src/components/request-summary.tsx`
- Modify: `ui/src/components/workflow-status.tsx`
- Modify: `ui/src/components/projection.test.tsx`
- Modify: `ui/src/pages/request-page.test.tsx`
- Modify: `ui/e2e/approve.spec.ts`
- Modify: `ui/e2e/conflict.spec.ts`
- Modify: `ui/e2e/recent-requests.spec.ts`

**Interfaces:**
- Consumes: `statusLabel`, `chipClass`, `ErrorBanner`
- Produces: review heading is `resolution.name` or the request id; link `Requests` to `/#requests`

- [ ] **Step 1: Write the failing test**

Replace the reconstructed-GET test in `ui/src/pages/request-page.test.tsx`:

```tsx
it("loads a reconstructed request and offers approval when the server allows it", async () => {
  const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
  render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
  expect(await screen.findByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Requests" })).toHaveAttribute("href", "/#requests");
  expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
  expect(screen.getByText("Pass")).toBeInTheDocument();
  expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Terraform plan summary" })).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Security findings" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Approval decision" })).toBeInTheDocument();
  expect(screen.queryByText("Unavailable after reload.")).not.toBeInTheDocument();
  expect(screen.queryByText("Outcome")).not.toBeInTheDocument();
  expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
  expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
});
```

Add a projection test:

```tsx
it("omits checkpoint fields the GET does not know", () => {
  const reloaded: RequestResponse = {
    ...posted,
    intent: null,
    resolution: { outcome: "resolved", name: "order-events", components: [] },
  };
  render(<Projection body={reloaded} />);
  expect(screen.queryByText("Unavailable after reload.")).not.toBeInTheDocument();
  expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
  expect(screen.queryByText("queue_processing")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
});

it("does not warn about destruction when the server flag is false", () => {
  render(
    <PlanSummary
      plan={{ add: 1, change: 0, destroy: 1, destructive_change_detected: false }}
    />,
  );
  expect(screen.getByText("1")).toBeInTheDocument();
  expect(screen.queryByText("Destructive change detected.")).not.toBeInTheDocument();
});
```

The second test passes before any `PlanSummary` edit. Leave `PlanSummary` unchanged.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/pages/request-page.test.tsx src/components/projection.test.tsx`

Expected: FAIL on `Unavailable after reload.` and the missing `Requests` link. The destructive-flag test PASSes immediately.

- [ ] **Step 3: Write minimal implementation**

`RequestPage` section order:

```tsx
<section aria-labelledby="request-review-heading">
  <p>
    <a
      href="/#requests"
      onClick={(event) => {
        event.preventDefault();
        onBack?.();
      }}
    >
      Requests
    </a>
  </p>
  {banner ? <ErrorBanner message={banner.message} tone={banner.tone} /> : null}
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
</section>
```

Add optional `onBack?: () => void` to `RequestPage`. `App` passes `onBack={() => openRegion("requests")}`.

`RequestSummary` heading is `body.resolution.name ?? body.request_id` at level 2, `id="request-review-heading"`. Under it, if `name` is set, render `<p className="meta">{body.request_id}</p>`. Render architecture, workload, interaction, capabilities, and components only when those values are present. Delete the `Unavailable after reload.` branch. Delete the Outcome term. When `outcome` differs from `workflow.workflow_status` (clarification is not rendered here), do not add an outcome row on this page.

`WorkflowStatus` keeps the no-apply sentence and the pull-request link. Remove the `Approval available` / `Approval not available` paragraph. Show workflow and security through `AuthoritativeValue` (already one label). Show stage once. If `workflow.error` is set, do not also repeat `error.stage` when it equals `current_stage`; show `Error type` once. The `Workflow error` heading is Task 9. This task only removes the duplicate approval sentence and the unavailable sentence.

In `projection.test.tsx`, replace the heading `Request` and the term `Outcome` expectations. The request heading is now level 2 and its name is `order-events`. Delete expectations that the visible text includes `Outcome` or `Approval available`. Keep the request id, the no-apply sentence, the plan counts, and the finding policy id. `renders the public submission fields` still expects architecture, workload, and components because that fixture includes them. `does not invent fields missing from a reconstructed GET` stops expecting `Unavailable after reload.` and still expects those fields to be absent.

Update Playwright specs that look for heading `Request review` to look for the resource name the fake server returns (`orders` on the indexed request, and the name shown after submit). Read the fake response in the running test if the name is `orders` for `req-browser` as well: `serve_fake_ui.py` sets `resource_name="order-events"` on the browser request and `orders` on the catalog row. After submit, the review heading is `order-events`. The direct `/requests/req-indexed` heading is `orders`. Replace `Request review` accordingly. Do not change the fake server.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS.

- [ ] **Step 5: Commit**

```
feat: lead request review with the resource

A reloaded checkpoint has no intent or architecture, so the page omits those fields instead of calling the gap a failure.
```

**Invariant:** `GET` is still the review source. `project_view` is not edited. Approval buttons still appear only when `approval_available` is true.

---

## Gate E — security, HITL, and outcomes

### Task 8: Trust sentences and button roles

**Files:**
- Modify: `ui/src/components/workflow-status.tsx`
- Modify: `ui/src/components/approval-panel.tsx`
- Modify: `ui/src/components/projection.test.tsx`
- Modify: `ui/src/components/approval-panel.test.tsx`
- Modify: `ui/src/pages/request-page.test.tsx`

**Interfaces:**
- Consumes: `body.approval_available`, `workflow.security_status`, `workflow.pull_request`
- Produces: the warn sentence, the closed sentence, `button-primary` on Approve and Confirm approval, `button-secondary` on Reject and Cancel

- [ ] **Step 1: Write the failing test**

Add to `projection.test.tsx`:

```tsx
it("says a warning can still reach a person", () => {
  render(<WorkflowStatus body={posted} />);
  expect(screen.getByText("Warnings still go to human review.")).toBeInTheDocument();
  expect(screen.queryByText("Approval is closed.")).not.toBeInTheDocument();
});

it("closes approval on a block without offering a decision", () => {
  const blocked: RequestResponse = {
    ...posted,
    outcome: "blocked",
    approval_available: false,
    workflow: {
      ...posted.workflow!,
      workflow_status: "blocked",
      security_status: "block",
    },
  };
  render(
    <>
      <WorkflowStatus body={blocked} />
      <ApprovalPanel body={blocked} client={{} as never} onResult={vi.fn()} />
    </>,
  );
  expect(screen.getByText("Approval is closed.")).toBeInTheDocument();
  expect(screen.queryByText("Warnings still go to human review.")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
});

it("places the pull request with the no-apply sentence", () => {
  const published: RequestResponse = {
    ...posted,
    approval_available: false,
    workflow: {
      ...posted.workflow!,
      workflow_status: "pr_created",
      security_status: "pass",
      pull_request: { url: "https://example.invalid/pull/7" },
    },
  };
  render(<WorkflowStatus body={published} />);
  expect(screen.getByText("Pull request created")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "https://example.invalid/pull/7" })).toBeInTheDocument();
  expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
  expect(screen.queryByText("Warnings still go to human review.")).not.toBeInTheDocument();
});
```

Import `ApprovalPanel` in that test file. Extend `approval-panel.test.tsx`:

```tsx
expect(screen.getByRole("button", { name: "Approve" })).toHaveClass("button-primary");
expect(screen.getByRole("button", { name: "Reject request" })).toHaveClass("button-secondary");
```

After opening the dialog:

```tsx
expect(screen.getByRole("button", { name: "Confirm approval" })).toHaveClass("button-primary");
expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("button-secondary");
```

The existing dialog name, Cancel focus, and immediate reject tests stay.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/projection.test.tsx src/components/approval-panel.test.tsx`

Expected: FAIL because the warn sentence and button classes are absent.

- [ ] **Step 3: Write minimal implementation**

In `WorkflowStatus`, after the security chip:

```tsx
{workflow?.security_status === "warn" && body.approval_available ? (
  <p>Warnings still go to human review.</p>
) : null}
{workflow?.security_status === "block" || workflow?.workflow_status === "blocked" ? (
  <p>Approval is closed.</p>
) : null}
```

Keep the pull-request paragraph in this section, above the findings, which `RequestPage` already renders after `WorkflowStatus`. Wrap Approve and Reject in `<div className="approval-actions">`. Set the button classes named above. Do not change `decide`, the dialog text, or `data-dialog-initial-focus`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS.

- [ ] **Step 5: Commit**

```
feat: show whether a person can still approve

Warn stays open for review, block closes the decision, and approve remains the confirmed action.
```

**Invariant:** Reject still does not open the dialog. Confirm approval still calls `client.decide(id, "approve")`. The dialog sentence is unchanged.

---

## Gate F — error taxonomy and narrow screens

### Task 9: Request-page error headings

**Files:**
- Modify: `ui/src/components/workflow-status.tsx`
- Modify: `ui/src/pages/request-page.tsx`
- Modify: `ui/src/pages/request-page.test.tsx`
- Modify: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `noticeTone`, `ErrorBanner`
- Produces: durable workflow errors use heading `Workflow error`

- [ ] **Step 1: Write the failing test**

```tsx
it("heads a durable workflow error once", () => {
  const body: RequestResponse = {
    ...posted,
    outcome: "error",
    approval_available: false,
    workflow: {
      ...posted.workflow!,
      workflow_status: "error",
      current_stage: "terraform",
      security_status: null,
      plan: null,
      findings: [],
      error: { stage: "terraform", error_type: "terraform_failed" },
    },
  };
  render(<WorkflowStatus body={body} />);
  expect(screen.getByRole("heading", { name: "Workflow error" })).toBeInTheDocument();
  expect(screen.getAllByText("Terraform")).toHaveLength(1);
  expect(screen.getByText("terraform_failed")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Not configured" })).not.toBeInTheDocument();
});
```

`terraform_failed` is not in the label map, so `statusLabel` returns `Terraform failed`. Assert that caption once, and `title` `terraform_failed` on that element. Do not assert the raw enum as visible text.

Add request-page tests:

```tsx
it("styles not-found as missing and does not call it a workflow error", async () => {
  // existing 404 fixture
  expect(await screen.findByRole("alert")).toHaveClass("notice-missing");
  expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Security findings" })).not.toBeInTheDocument();
});

it("styles a network failure as an error notice without a workflow heading", async () => {
  expect(await screen.findByRole("alert")).toHaveClass("notice-error");
  expect(screen.getByText("The API could not be reached.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
});

it("styles an approval conflict without replacing the server message", async () => {
  expect(await screen.findByRole("heading", { name: "Approval conflict" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveClass("notice-conflict");
  expect(screen.getByText("Rejected")).toBeInTheDocument();
});
```

Keep loading and polling assertions on the existing strings `Loading request.` and `Checking this request.`

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/pages/request-page.test.tsx src/components/projection.test.tsx`

Expected: FAIL because `Workflow error` is not rendered and the alert has no `notice-missing` class until `tone` is passed. Task 6 already added `tone` to the request page if the typecheck required it. This task fails on the heading and the class assertions if those were not asserted before.

- [ ] **Step 3: Write minimal implementation**

In `WorkflowStatus`, when `workflow.error` is set:

```tsx
<h3>Workflow error</h3>
```

Render `Error stage` only when `workflow.error.stage` is different from `workflow.current_stage`. Always render `Error type` once through `AuthoritativeValue`.

When `findings` is empty and status is `pending`, `running`, `approved`, or `error`, `Findings` returns null. When `findings` is empty and status is `awaiting_approval`, `blocked`, `rejected`, or `pr_created`, `Findings` renders `<p>No findings were returned.</p>` and no table. Pass `workflowStatus` into `Findings`:

```tsx
export function Findings({
  findings,
  workflowStatus,
}: {
  findings: FindingDTO[];
  workflowStatus?: string | null;
})
```

`RequestPage` passes `body.workflow?.workflow_status`. Update the projection helper to pass it too.

`request-page` already maps `noticeTone`. Confirm 404 uses `noticeTone("request_not_found")`, network uses `error`, and `approval_conflict` uses `conflict`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS.

- [ ] **Step 5: Commit**

```
feat: distinguish workflow errors from security blocks and conflicts

A failed stage, a missing request, and an approval conflict are different operator states.
```

**Invariant:** Server messages are not rewritten. `approval_conflict` still replaces the body with `result.request`.

### Task 10: Narrow findings and actions

**Files:**
- Modify: `ui/src/components/findings.tsx` only if the stack from Task 3 is incomplete
- Modify: `ui/src/styles.css` only if the media query from Task 2 is incomplete
- Test: `ui/src/components/findings.test.tsx`

**Interfaces:**
- Consumes: `.findings-table`, `.finding-stack`, `.approval-actions`
- Produces: a list named `Security findings` in addition to the table

- [ ] **Step 1: Write the failing test**

Create `ui/src/components/findings.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Findings } from "./findings";

describe("findings", () => {
  it("keeps a table and a stacked list with the same caption", () => {
    render(
      <Findings
        workflowStatus="awaiting_approval"
        findings={[{ policy_id: "SQS_ENCRYPTION", status: "pass", severity: "high" }]}
      />,
    );
    expect(screen.getByRole("table", { name: "Security findings" })).toHaveClass("findings-table");
    const list = screen.getByRole("list", { name: "Security findings" });
    expect(list).toHaveClass("finding-stack");
    expect(screen.getAllByText("Pass").length).toBeGreaterThan(0);
    expect(screen.getAllByText("High").length).toBeGreaterThan(0);
    expect(screen.getAllByTitle("pass").length).toBeGreaterThan(0);
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
  });

  it("hides an empty in-progress gate and reports an empty reviewed gate", () => {
    const { rerender } = render(<Findings findings={[]} workflowStatus="pending" />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("No findings were returned.")).not.toBeInTheDocument();
    rerender(<Findings findings={[]} workflowStatus="blocked" />);
    expect(screen.getByText("No findings were returned.")).toBeInTheDocument();
  });
});
```

Add `aria-label="Security findings"` on the `<ul>` so the list has an accessible name. The table keeps its visually hidden caption.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/components/findings.test.tsx`

Expected: FAIL if the list has no accessible name. If Task 3 already satisfies the test, record that and do not rewrite the component.

- [ ] **Step 3: Write minimal implementation**

Add `aria-label="Security findings"` to `.finding-stack`. Confirm `styles.css` hides `.findings-table` and shows `.finding-stack` only inside `@media (max-width: 40rem)`, and that `.approval-actions button` is `width: 100%` there. Do not change the breakpoint value.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm test`

Expected: PASS. jsdom does not apply the media query. Visibility at 390px is asserted in Task 11.

- [ ] **Step 5: Commit**

Commit only if this task changed files. If it changed nothing, do not create an empty commit.

```
feat: stack security findings on a narrow screen

Policy, status, and severity stay labeled when the table no longer fits.
```

**Invariant:** Wide layout still exposes the table. Status text remains present in both structures.

---

## Gate G — portfolio and visual acceptance

### Task 11: Deterministic portfolio spec

**Files:**
- Create: `ui/e2e/portfolio.spec.ts`
- Modify: none of the production UI unless an assertion shows a design miss. If the 1440×900 box fails, stop and report it. Do not edit production code in this task to force a pass.

**Interfaces:**
- Consumes: the running Vite app and `page.route` for `/api/`, `/health`, and `/ready`
- Produces: Playwright coverage of the five portfolio states plus auth, capability unavailable, workflow error, and a 390px viewport

- [ ] **Step 1: Write the failing test**

Create `ui/e2e/portfolio.spec.ts`. Intercept browser requests whose pathname is `/health`, `/ready`, or starts with `/api/`. Fulfill JSON. Do not change `tests/browser/serve_fake_ui.py`.

Health and ready return `{ status: "ok" }` and `{ status: "ready" }`.

Catalog `GET /api/v1/requests` returns three rows:

| request_id | name | workflow_status | security_status | approval_available |
|---|---|---|---|---|
| `req-order-events` | `order-events` | `awaiting_approval` | `pass` | true |
| `req-public-bucket` | `public-uploads` | `blocked` | `block` | false |
| `req-billing-export` | `billing-export` | `pr_created` | `warn` | false |

Detail fixtures:

- Awaiting: name `order-events`, workflow `awaiting_approval`, security `pass`, plan `{ add: 4, change: 0, destroy: 0, destructive_change_detected: false }`, findings `SQS_ENCRYPTION/pass/high` and `SQS_QUEUE_VISIBILITY/pass/medium`, `approval_available: true`, `intent: null`, resolution name only, `terraform_apply: "not_executed"`.
- Blocked: workflow `blocked`, security `block`, plan `{ add: 4, change: 0, destroy: 1, destructive_change_detected: true }`, findings include `S3_PUBLIC_ACCESS/block/critical`, `approval_available: false`.
- Published: workflow `pr_created`, security `pass`, `pull_request.url` `https://github.com/example/platform/pull/7`, `approval_available: false`.
- Warn: workflow `awaiting_approval`, security `warn`, one finding `LAMBDA_RUNTIME/warn/medium`, `approval_available: true`, plan add 4.
- Workflow error: workflow `error`, `current_stage` `terraform_plan`, `error` `{ stage: "terraform_plan", error_type: "terraform_failed" }`, `plan: null`, `findings: []`, `approval_available: false`.

Assertions:

1. After Continue, the catalog shows links `order-events`, `public-uploads`, and `billing-export`, chips `Awaiting approval`, `Pass`, `Blocked`, `Block`, `Pull request created`, and `Warn`.
2. Open `order-events` at viewport `{ width: 1440, height: 900 }`. Expect heading `order-events`, text `Pass`, `Terraform apply was not executed.`, `Add`, `4`, both policy ids, `Approve`, and `Reject request`. The Approve button's `boundingBox()` satisfies `y + height <= 900`.
3. Open the blocked fixture. Expect `Destructive change detected.`, `Block`, `Approval is closed.`, and zero `Approve` buttons.
4. Open the published fixture. Expect `Pull request created`, the pull request URL, and `Terraform apply was not executed.`
5. Open the warn fixture. Expect `Warn`, `Warnings still go to human review.`, and `Approve`.
6. Fresh context, no secret: expect the memory sentence and `Continue`.
7. Compose `POST /api/v1/requests` returns 503 `capability_unavailable` with the exact intent message from Global Constraints. Expect heading `Not configured` and that message.
8. Open the workflow-error fixture. Expect heading `Workflow error` and text `Terraform failed`. Expect no `Approve` button.
9. At `{ width: 390, height: 844 }`, open the awaiting fixture. The table is hidden (`not.toBeVisible()`), the list `Security findings` is visible, and `Approve` is visible.

Use `continueAsOperator` from `ui/e2e/operator.ts`. A full `page.goto` clears the secret; fill it again after any `goto`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx playwright test e2e/portfolio.spec.ts`

Expected: FAIL until the spec's routes match the app, or PASS if Tasks 1–10 already implement the hierarchy. A failure of `y + height <= 900` stops the batch. Do not edit CSS font sizes, hide the findings, or remove `Terraform apply was not executed.` to satisfy it.

- [ ] **Step 3: Write minimal implementation**

The spec is the implementation. No production edit in the passing case.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx playwright test e2e/portfolio.spec.ts e2e/approve.spec.ts e2e/conflict.spec.ts e2e/recent-requests.spec.ts`

Expected: PASS. Delete `ui/test-results` if Playwright creates it. Do not commit screenshots.

- [ ] **Step 5: Commit**

Commit only `ui/e2e/portfolio.spec.ts`.

```
test: cover the control-plane review states in the browser

The catalog, the approval gate, a block, a pull request, and a warning need one deterministic spec.
```

**Invariant:** The fake API server and the production API are unchanged. Portfolio data is a browser route fixture.

---

## Gate H — final regression

### Task 12: Deterministic validation

**Files:**
- Modify: none unless a command fails because this batch left an assertion behind. A fix for a test this plan owns is a separate commit. A failure in `src/iac_agent/` stops the batch; do not edit the backend to suit the UI.

- [ ] **Step 1: Confirm the diff surface**

Run:

```bash
git diff --name-only a64102664002eb171ab6e72f5b2b2baec5ea044e
git diff --check
```

Expected names are only under `ui/` plus this plan if it is already committed. No `package.json`, `package-lock.json`, `src/iac_agent/`, `terraform/`, or `docs/api.md`.

Search the UI diff for forbidden storage:

```bash
git diff -U0 a64102664002eb171ab6e72f5b2b2baec5ea044e -- ui/src | rg "localStorage|sessionStorage|document.cookie|VITE_"
```

Expected: no matches. `rg` exit 1 means the search is clean.

- [ ] **Step 2: Run the UI suites**

```bash
cd ui && npm test
cd ui && npm run build
cd ui && npx playwright test
```

Expected: unit tests PASS, `tsc --noEmit` and the Vite build PASS, Playwright PASS.

- [ ] **Step 3: Run the API regression**

From the repository root:

```bash
.venv/bin/python -m ruff check ui
.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q
```

`ruff check ui` may report that `ui` is excluded. If ruff has nothing to check, that is success. Do not format Terraform. Do not run `real_tool`, `real_llm`, or docker tests.

Expected: pytest PASS. A failure outside `ui/` means this batch touched a contract. Stop.

- [ ] **Step 4: Commit**

Do not create an empty commit. If Step 1–3 pass with no further edits, this task has no commit.

**Invariant:** The approved design spec is still `a64102664002eb171ab6e72f5b2baec5ea044e` plus no content change. Backend workflow, intent, resolver, modules, `TerraformRunner`, `PlanAnalyzer`, Checkov, policy decisions, approval semantics, source control, SQLite, `request_index`, `RuntimeCapabilities`, authentication, and success DTOs are untouched.

## Self-review

The plan was checked against the design before commit.

| Design requirement | Task |
|---|---|
| One human label, raw enum not beside it | 1, 3 |
| Tokens, chips, buttons, notices | 2 |
| Shell, nav landmark, runtime mark | 4 |
| Memory-only secret and reload | 4 |
| Catalog name, id, chips, no approval sentence | 5 |
| Capability notice versus other compose errors | 6 |
| Resource heading, omitted checkpoint fields, back link | 7 |
| Plan counts and destructive flag | 7, existing `PlanSummary` |
| Warn, block, approve, reject, pull request | 8 |
| Error headings and untouched server messages | 6, 9 |
| Loading and polling sentences | 7, 9 |
| Stacked findings and full-width actions | 2, 10, 11 |
| Five portfolio states and 1440×900 | 11 |
| No dependency, no API change | Global Constraints, Task 12 |

No placeholder tasks remain. `statusLabel` and `noticeTone` keep the same names in every task. `terraform_plan` and `publish` are display labels for stage strings the UI already receives.

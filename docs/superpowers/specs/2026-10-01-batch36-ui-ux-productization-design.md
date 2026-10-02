# Batch 36 — operator UI productization

Status: design, awaiting approval. This document is not an implementation plan and is not permission to change production code.

Direction: control-plane review workspace.

Baseline: `origin/main` `24edf9a362608d3466be8e67a2d001e782cb6d66`, the merge of pull request 19. Discovery rendered the operator UI from that tree through `tests/browser/serve_fake_ui.py` and `ui` `npm run dev`. Warn, block, workflow error, and `capability_unavailable` were inspected with browser fixtures. Production code was not changed during discovery.

## 1. Problem statement

The functional v1 operator UI is a two-page React client. It submits natural language, lists durable requests, and reviews plan, findings, and approval. The presentation still reads as a form that prints server enums.

`AuthoritativeValue` in `ui/src/components/authoritative-value.tsx` shows a human caption and the raw enum on the same line. Review pages therefore say "Pass pass", "Warn warn", "Block block", "Error error", and "Awaiting approval awaiting_approval". Pass, warn, and block share one text color. Approve and Reject share one button style. Recent requests are stacked definition lists. The review page leads with request metadata. The human decision and the pull-request result sit below that stack.

A ten-second screenshot does not yet show an infrastructure control plane: a named change, a security gate, a Terraform plan, a human decision, and a GitHub pull request as the mutation boundary.

Batch 36 changes presentation only. The UI remains a client of the existing control plane.

## 2. Design principles

- Infrastructure engineering is the product. The model interprets intent. Deterministic controls evaluate the change. A person approves or rejects it. Approved publication may create a GitHub pull request. Terraform apply does not run. That is the trust model. It is not permanent copy on every panel.
- Keep the light, off-white foundation in `ui/src/styles.css`. Evolve that file. Add no component library and no utility framework.
- Show each status once, as words. Color supports the word and never replaces it.
- Lead the review with the resource, the gate, the plan, and the human decision.
- Omit durable fields the current GET projection does not know. Do not describe that omission as a workflow failure.
- Preserve routes, API contracts, approval semantics, and session behavior.

Display identity, in the shell only:

```
IaC Agent
Infrastructure control plane
```

The repository name remains `iac-agent-platform`.

The interface does not use AI-powered badges, chatbot transcripts, assistant avatars, sparkles, cyberpunk styling, or generic SaaS-dashboard decoration.

## 3. Information architecture

Routes stay exactly those in `ui/src/router.ts`:

| Path | Screen |
|---|---|
| `/` | Compose, with the request catalog on the same page |
| `/requests/{request_id}` | Review of one durable request |
| anything else | Existing "Page not found." |

No third route. No client-side filter, search, or sort. The catalog order remains the order `GET /api/v1/requests` already returns.

```
Shell
  IaC Agent
  Infrastructure control plane
  Runtime mark          Compose    Requests
        |
        +-- /  Compose
        |     infrastructure textarea
        |     non-durable result, when the create response has no workflow
        |     configuration notice, when the server says capability_unavailable
        |     catalog rows
        |     open-by-id, secondary
        |
        +-- /requests/{id}  Review
              resource name
              workflow and security
              plan counts
              findings
              human decision, or the closed-gate statement
              pull request, when the DTO has one
```

The shell landmark is `<nav aria-label="Primary">`. Compose moves to `/` and focuses the composer. Requests moves to `/` and focuses the catalog. On a review page, Requests is the way back to the catalog, and the review page also has its own "Requests" link so the return does not depend on remembering the shell.

## 4. Shell

```
+------------------------------------------------------------------+
| IaC Agent                          Compose     Requests          |
| Infrastructure control plane       Runtime ready                 |
+------------------------------------------------------------------+
```

`HealthIndicator` remains the only runtime source. It already calls `GET /health` and `GET /ready` without the operator secret.

| Probes | Visible mark |
|---|---|
| health `ok` and ready `ready` | Runtime ready |
| health `ok` and ready is anything else | Runtime not ready |
| health failed | Runtime unreachable |

The mark is words plus a small dot of the same meaning. "Runtime ready" means the API process responded and the state plane is open. It does not mean GitHub or the interpreter is configured or reachable. There is no new capability endpoint. The current two-sentence health block is removed from the page body.

Below `40rem` the title, the nav, and the runtime mark wrap onto separate lines. The nav remains a landmark.

## 5. Authentication

The operator secret stays in React state in `ui/src/app.tsx`. Reload clears it. The client continues to send `Authorization: Bearer` only from that memory. No `localStorage`, `sessionStorage`, cookie, or `VITE` credential.

Until a secret is set, the page is the shell plus the form. Compose and the catalog stay unmounted, as they do today.

```
+----------------------------------------------+
| IaC Agent                                    |
| Infrastructure control plane                 |
| Runtime ready                                |
|                                              |
| Operator secret                              |
| [ password                                 ] |
| This secret stays in this tab's memory.      |
| Reloading the page clears it.                |
| [ Continue ]                                 |
+----------------------------------------------+
```

Continue still ignores an empty or whitespace-only value. A 401 from any later call still clears the secret and returns to this form. The server message "Authentication is required." is unchanged and is not shown as a workflow error.

## 6. Composer

The infrastructure textarea remains the primary action on `/`. It stays a labeled form, not a transcript. There are no message bubbles, avatars, or suggestion chips.

```
+------------------------------------------------------------------+
| New request                                                      |
| Describe the infrastructure. A durable workflow opens on its     |
| own page.                                                        |
|                                                                  |
| Infrastructure request                                           |
| [                                                                ] |
| [ Submit request ]                                               |
+------------------------------------------------------------------+
```

Submit behavior is unchanged:

- An empty description sets the existing local sentence "Describe the infrastructure before submitting."
- Submit posts `{ natural_language_request }` and disables the button while the call is in flight.
- HTTP 201 with a workflow navigates to `/requests/{request_id}`. The review page then loads the GET projection.
- `clarification_required` and `unsupported` stay on `/` as a non-durable result. The panel title remains "Unsaved result". It shows the outcome once, the resolution field, reason, detail, and allowed values the body actually contains, and the existing sentence "This result is not saved. Refreshing clears it."
- `capability_unavailable` uses the configuration notice in section 14. The server `message` is shown verbatim. The existing sentence "This request was not saved." remains under that notice. The same notice is used when approve returns `capability_unavailable`, including "Source-control publishing is not configured. Set GITHUB_OWNER, GITHUB_REPOSITORY, GITHUB_COMMIT_AUTHOR_NAME, GITHUB_COMMIT_AUTHOR_EMAIL, and GITHUB_TOKEN."
- Every other compose failure uses the notice class in section 14 and shows the server or client message unchanged.

## 7. Request catalog

The catalog region is `#requests` on `/`. Each row is one request. The resource name is the link. The request id is the secondary line, in monospace. Workflow and security are chips. Human action waiting is the "Awaiting approval" chip itself, so the row does not also say "Approval available" or "Decision waiting".

```
+------------------------------------------------------------------+
| Recent requests                                                  |
|                                                                  |
| order-events                    Awaiting approval          Pass  |
| req-order-events                                                 |
|                                                                  |
| public-uploads                  Blocked                   Block  |
| req-public-bucket                                                |
|                                                                  |
| billing-export                  Pull request created       Warn  |
| req-billing-export                                               |
+------------------------------------------------------------------+

Open a saved request
[ Request id                                                     ]
[ Open request ]
```

When `name` is null, the request id is the link and the secondary id line is omitted. When `security_status` is null, the security chip is omitted. The timestamp may sit in the row's accessible description or `title`. It is not a third visual column.

Empty catalog copy:

"No indexed requests. A checkpoint created before the durable index can still be opened by request id."

Open-by-id keeps its current behavior and sits below the list, in a quieter panel. The button is secondary.

## 8. Request detail hierarchy

The review page answers, in order: which resource, which workflow state, which security result, what the plan contains, whether a person must act, and what approval will do.

```
+------------------------------------------------------------------+
| Requests                                                         |
|                                                                  |
| order-events                                                     |
| req-order-events                                                 |
|                                                                  |
| Awaiting approval          Pass                                  |
| Terraform apply was not executed.                                |
|                                                                  |
| Plan                                                             |
| Add              Change             Destroy                      |
| 4                0                  0                            |
|                                                                  |
| Security findings                                                |
| SQS_ENCRYPTION          Pass              High                   |
| SQS_QUEUE_VISIBILITY    Pass              Medium                 |
|                                                                  |
| Approval                                                         |
| Reject sends immediately and does not ask for confirmation.      |
| [ Approve ]  [ Reject request ]                                  |
+------------------------------------------------------------------+
```

The resource name is the page heading. When `resolution.name` is null, the request id is the heading and is not repeated on a second line. Otherwise the request id is directly under the name, in monospace. Workflow status, security status, and "Terraform apply was not executed." form the status cluster. Plan counts follow. Findings follow the plan. The human decision follows findings. A pull request, when present, is in the status cluster so the publication result is visible with the resource.

The page does not lead with a metadata definition list. Outcome is not shown when it repeats `workflow_status`, which is how `project_view` builds a durable read. Stage is shown once, as a quiet line under the chips ("Stage: Approval"), using the human label. Workload, interaction, capabilities, architecture, and components render only when the response body actually contains them. The durable GET does not contain them. The review page therefore omits them. It does not say "Unavailable after reload."

A 1440×900 review of the portfolio awaiting-approval state, with two findings, shows the resource, both chips, the no-apply line, the plan counts, the findings, and the approval actions without scrolling. A longer findings list may extend below that viewport. Loading remains the sentence "Loading request." Polling remains the sentence "Checking this request." Both keep `role="status"`.

"Requests" at the top of the page navigates to `/#requests`.

## 9. Status system

Visible text is the human label once. The raw enum is the element's `title`, available to pointer users and to tests, and is not painted beside the label. Backend enums are unchanged.

| Enum | Visible label | Role |
|---|---|---|
| `pass` | Pass | Security result |
| `warn` | Warn | Security result; review may continue |
| `block` | Block | Security result; approval is closed |
| `awaiting_approval` | Awaiting approval | Human action is waiting |
| `pending` | Pending | Workflow still running |
| `running` | Running | Workflow still running |
| `approved` | Approved | Intermediate, after the person approves and before publication settles |
| `rejected` | Rejected | Person rejected the change |
| `blocked` | Blocked | Workflow stopped at the security gate |
| `error` | Error | Workflow could not obtain a result |
| `pr_created` | Pull request created | Publication result |
| `destructive_change_detected` | Destructive change detected. | Plan warning sentence, unchanged |

Stage labels follow the same single-label rule: `plan_analysis` is "Plan analysis", `security_gate` is "Security gate", `source_control` is "Source control", `pr_created`'s stage `source_control` stays a stage line and does not replace the workflow chip.

Color tokens extend `:root` in `ui/src/styles.css`. Text on each pale surface is dark. The word is always present.

| Token pair | Used for |
|---|---|
| `--color-status-pass-text` / `--color-status-pass-surface` | Pass |
| `--color-status-warn-text` / `--color-status-warn-surface` | Warn |
| `--color-status-block-text` / `--color-status-block-surface` | Block, and the destructive plan border |
| `--color-status-attention-text` / `--color-status-attention-surface` | Awaiting approval. Blue family already used by `--color-focus` |
| `--color-status-published-text` / `--color-status-published-surface` | Pull request created. Distinct from Pass |
| `--color-status-neutral-text` / `--color-status-neutral-surface` | Pending, Running, and Approved. The word distinguishes them |
| `--color-status-rejected-text` / `--color-status-rejected-surface` | Rejected. Stone text with a stronger border, not the block red |
| `--color-notice-config-text` / `--color-notice-config-border` | `capability_unavailable` |
| `--color-notice-error-text` / `--color-notice-error-border` | Workflow error |
| `--color-notice-conflict-text` / `--color-notice-conflict-border` | Approval conflict and `request_exists` |

Pass is the only green. Pull request created does not reuse it. Block is the only security red. Workflow error uses the error notice, not the block chip colors. Awaiting approval uses the attention chip, so a waiting decision is not painted as a failure or as a pass.

Findings and chips use the same security tokens, so a "Block" cell and a "Block" chip match.

## 10. Plan presentation

The plan region keeps Add, Change, and Destroy. Values stay monospace and large enough to scan. The existing three-column grid remains, and below `40rem` it remains one column, as `.plan-counts` already does.

When `plan` is null, the region says "No plan summary was returned." It does not show zeros.

When `destructive_change_detected` is true, the panel keeps the danger border and the sentence "Destructive change detected." The destroy count is still just the count. The UI does not invent a second rule from `destroy > 0` when the boolean is false.

Raw Terraform plan JSON is not requested and not rendered.

## 11. Findings presentation

Wide layout stays a table with columns Policy, Status, and Severity. The caption stays "Security findings" and stays visually hidden, associated with the table. Policy ids stay monospace. Status and severity are human labels once, with the raw enum on `title`.

```
Policy                  Status        Severity
SQS_ENCRYPTION          Pass          High
LAMBDA_RUNTIME          Warn          Medium
S3_PUBLIC_ACCESS        Block         Critical
```

Below `40rem`, the table is replaced by a stacked list. Each finding is its own block. The column headers become the block's labels, so policy, status, and severity are never squeezed onto one line:

```
Policy
SQS_ENCRYPTION
Status
Pass
Severity
High
```

The stacked list uses the same visually hidden caption.

When `findings` is empty and the workflow is `pending`, `running`, `approved`, or `error`, the findings region is omitted. The polling line or the workflow-error notice already explains that the gate has no result yet. When `findings` is empty on `awaiting_approval`, `blocked`, `rejected`, or `pr_created`, the region says "No findings were returned."

Security sentences, in addition to the chip:

| Condition | Sentence |
|---|---|
| `security_status` is `warn` and `approval_available` is true | Warnings still go to human review. |
| `security_status` is `block` or `workflow_status` is `blocked` | Approval is closed. |

Warn and pass stay different chips and different sentences. A warn request does not say it passed. A blocked request does not render `ApprovalPanel`.

## 12. Human approval

`ApprovalPanel` still renders only when `approval_available` is true. The server sets that flag for `awaiting_approval` only. The UI does not compute its own gate.

```
+------------------------------------------------------------------+
| Approval                                                         |
| Reject sends immediately and does not ask for confirmation.      |
| [ Approve ]              [ Reject request ]                      |
+------------------------------------------------------------------+

Dialog, after Approve:

Approval resumes the workflow and publication may create a pull request.
Terraform apply will not run.
[ Cancel ]    [ Confirm approval ]
```

Approve is the primary button and still opens the existing `<dialog>`. Reject is secondary and still sends immediately. The confirmation sentence stays verbatim. Cancel keeps initial focus. Confirm approval is the primary action inside the dialog. The dialog element stays a native dialog so `showModal` and the existing focus return continue to work. The dialog uses the panel surface, the panel border, the body type size, and `--space-4` padding.

Below `40rem`, Approve and Reject stack to the full content width. Approve remains first.

While a decision request is in flight, both buttons stay disabled and the region stays `aria-busy`, as today.

## 13. Pull request created

When `workflow.pull_request.url` is present, the status cluster includes the workflow chip "Pull request created" and the link. The link text is the URL. The no-apply sentence remains in that cluster.

```
billing-export
req-billing-export

Pull request created          Warn
https://github.com/example/platform/pull/7
Terraform apply was not executed.
```

The UI does not add GitHub actions. Approval controls stay absent because `approval_available` is false.

## 14. Error taxonomy

Each class has its own notice. The server `message` is the body. The UI does not rewrite contract strings.

| Class | Source | Notice | What stays on screen |
|---|---|---|---|
| Capability unavailable | `error` `capability_unavailable` | Configuration border. Heading "Not configured". Verbatim `message` | Composer draft, or the review already loaded. Approval controls remain if the request is still awaiting approval |
| Workflow error | workflow `workflow_status` `error` | Error border. Heading "Workflow error". Stage and error type, each once | No approval controls. No empty findings table. No zero plan |
| Call failure | `internal_error`, `invalid_request`, `invalid_request_id`, `invalid_approval`, or the client network sentence "The API could not be reached." | Error border. No extra heading. The existing message is the alert | The screen that made the call |
| Security block | workflow `blocked` and/or security `block` | Block chip plus "Approval is closed." This is a completed gate, not an error notice | Plan and findings. No approval controls |
| Approval conflict | `error` `approval_conflict` | Conflict border. Heading "Approval conflict". Message remains "This request cannot accept that decision." | The embedded `request` replaces the view, as today |
| Duplicate create | `error` `request_exists` | Conflict border. No "Approval conflict" heading. Message remains "Request already exists." | Composer. Nothing is navigated |
| Missing request | `error` `request_not_found` | Missing border. Message remains "Request not found." | No review stack |

## 15. Durable data limit

`project_view` in `src/iac_agent/api/project.py` sets `intent` to null and returns a resolution with the resource name only. Batch 36 does not change that function, the success DTO, or checkpoint contents.

The review page renders `resolution.name`, workflow, plan, findings, approval availability, and `pull_request`. It omits intent, architecture, workload, interaction, capabilities, and components when they are absent. The sentence "Unavailable after reload." is removed.

Non-durable compose results still show the resolution fields the create response includes, because those responses never become a checkpoint read.

## 16. Responsive behavior

The existing `40rem` breakpoint remains the only breakpoint.

| Region | Below 40rem |
|---|---|
| Shell | Title, nav, and runtime mark wrap |
| Page padding | Existing `main` padding reduction |
| Plan | One metric per row |
| Findings | Stacked blocks from section 11 |
| Approval | Approve, then Reject, each full width |
| Catalog row | Name, then id, then chips wrapping under the name |
| Dialog | Existing `max-width: min(32rem, calc(100vw - 2rem))` |

## 17. Accessibility preservation

These behaviors stay:

- Every control keeps its label.
- `:focus-visible` remains the focus treatment.
- Error and conflict notices use `role="alert"`.
- Loading and polling copy keep `role="status"`.
- The composer form and the approval region keep `aria-busy` while a call is in flight.
- The dialog keeps `aria-labelledby`, `showModal` when available, initial focus on Cancel, and focus return to Approve on cancel.
- The findings caption stays visually hidden and still names the table or the stacked list.
- Status chips include the visible word, so meaning does not depend on color.
- The new primary nav is a `nav` landmark with `aria-label="Primary"`.
- The review page link "Requests" is a real link to `/#requests`.

The operator secret input stays `type="password"` and `autoComplete="off"`.

## 18. Design-system changes

All of this lives in `ui/src/styles.css` and in `className`s on the existing components. No new package.

Add:

- The status and notice tokens in section 9.
- A type scale that keeps the system sans and system mono: product title, page heading, section heading, body, and a smaller meta line for request ids.
- Spacing that uses the existing `--space-1` through `--space-5` scale. Catalog rows and the status cluster use that scale rather than ad-hoc margins.
- `.chip` plus one modifier per status role.
- `.button-primary` and `.button-secondary`. The default button style remains the secondary look so unmarked buttons do not become primary by accident.
- `.catalog-row` for the request list.
- `.notice-config`, `.notice-error`, `.notice-conflict`, and `.notice-missing`.
- `.finding-stack`, shown below `40rem`, with the table hidden at that width. Above `40rem` the stack is hidden and the table is shown.
- `.technical` for monospace request ids, policy ids, and plan counts.

`AuthoritativeValue` becomes the single place that maps an enum to one visible label and a `title` of the raw value. Call sites stop rendering a second `<code>` of the same value.

Components that change presentation, and only presentation:

- `ui/src/styles.css`
- `ui/src/app.tsx`
- `ui/src/pages/compose-page.tsx`
- `ui/src/pages/request-page.tsx`
- `ui/src/components/authoritative-value.tsx`
- `ui/src/components/health-indicator.tsx`
- `ui/src/components/request-summary.tsx`
- `ui/src/components/workflow-status.tsx`
- `ui/src/components/plan-summary.tsx`
- `ui/src/components/findings.tsx`
- `ui/src/components/approval-panel.tsx`
- `ui/src/components/error-banner.tsx`
- `ui/src/components/request-form.tsx`
- `ui/src/components/open-request.tsx`

Tests that assert the doubled caption-plus-enum string will change with that presentation. Playwright specs keep finding Approve, Reject request, Confirm approval, and Cancel by accessible name.

No file under `src/iac_agent/`, `tests/` outside `ui`, `terraform/`, `docs/api.md`, or `package.json` is part of this design.

## 19. Portfolio screenshot states

These states are already representable with the current DTOs. No marketing asset is created in this batch.

| Shot | State the UI must make obvious |
|---|---|
| A. Catalog | Three rows: awaiting approval with Pass, blocked with Block, pull request created. Names lead. Ids are secondary |
| B. Awaiting approval | Resource, Pass chip, plan counts, findings, Approve and Reject, "Terraform apply was not executed." |
| C. Blocked change | Destructive plan sentence, a Block finding, "Approval is closed.", no approval controls |
| D. Pull request created | Pull request created chip, the URL, the no-apply sentence |
| E. Warn | Warn chip, a warn finding, "Warnings still go to human review.", Approve and Reject still present |

## 20. Backend and API boundaries

The UI keeps calling only:

- `POST /api/v1/requests`
- `GET /api/v1/requests`
- `GET /api/v1/requests/{request_id}`
- `POST /api/v1/requests/{request_id}/approval`
- `GET /health`
- `GET /ready`

Success DTO fields are unchanged. `terraform_apply` remains `not_executed`. `project_view` is unchanged. Error codes and messages are unchanged.

Preserved product boundaries:

- Backend workflow, `ArchitectureIntent`, the deterministic resolver, and Terraform modules stay as they are.
- `PlanAnalyzer`, security policy decisions, and Checkov stay as they are.
- HITL semantics, approval conflict semantics, and source-control publishing stay as they are.
- SQLite, `request_index`, and `RuntimeCapabilities` stay as they are.
- The authentication boundary stays the in-memory operator secret.
- Terraform apply does not run. Terraform destroy does not run.
- No remote or public deployment, RBAC, or multi-user work.

## 21. Non-goals

- No backend workflow change.
- No `ArchitectureIntent` change.
- No deterministic resolver change.
- No Terraform module change.
- No `PlanAnalyzer` change.
- No security-policy change.
- No Checkov change.
- No HITL semantic change.
- No approval-conflict semantic change.
- No source-control publishing change.
- No SQLite change.
- No `request_index` change.
- No `RuntimeCapabilities` change.
- No authentication-boundary change.
- No API success DTO change.
- No `project_view` change.
- No new persistence for intent, architecture, or components.
- No Terraform apply.
- No Terraform destroy.
- No remote or public deployment work.
- No RBAC.
- No multi-user work.
- No new npm or Python dependency.
- No Tailwind, Material UI, Chakra, Ant Design, or shadcn.
- No catalog filter, search, or sort.
- No marketing images.

## 22. Acceptance criteria

1. The shell shows "IaC Agent" and "Infrastructure control plane", a primary nav with Compose and Requests, and a runtime mark whose words are only Runtime ready, Runtime not ready, or Runtime unreachable.
2. The runtime mark does not mention GitHub, OpenAI, or capability configuration.
3. Reload clears the operator secret. The secret is not written to storage.
4. The auth screen explains, once, that the secret stays in tab memory and reload clears it.
5. The composer remains a single labeled textarea and a submit button. Clarification-required and unsupported results stay on `/` and still say the result is not saved.
6. `capability_unavailable` renders the configuration notice and the server message unchanged, including both the interpreter message and the source-control message.
7. A catalog row leads with the resource name, shows the request id in monospace, and shows workflow and security as single labels. It does not repeat "Approval available".
8. The review page heading is the resource name. The first screenful of an awaiting-approval review contains the status chips, the no-apply sentence, the plan counts, the findings, and the approval actions.
9. No visible string pairs a label with its own raw enum. The raw enum is present only as `title` or other non-visible metadata.
10. Pass, Warn, and Block are distinct words and distinct token pairs. Warn with approval available includes "Warnings still go to human review." Block includes "Approval is closed." and renders no approval controls.
11. Plan counts remain Add, Change, and Destroy. A true `destructive_change_detected` still shows "Destructive change detected."
12. Approve still opens the confirmation dialog whose sentence is unchanged. Reject still submits immediately. Cancel still takes initial focus.
13. A pull request URL in the DTO is visible in the status cluster beside "Pull request created" and "Terraform apply was not executed."
14. Capability unavailable, workflow error, security block, approval conflict, and request-not-found do not share one notice style.
15. A durable review with null intent and a name-only resolution omits the missing fields and does not say "Unavailable after reload."
16. Below `40rem`, findings are stacked blocks, plan metrics are one per row, and Approve and Reject are full width.
17. Labels, focus-visible, `role="alert"`, `role="status"`, `aria-busy`, dialog focus, and the findings caption still hold. A `nav` landmark exists.
18. No new dependency is added. No file outside `ui/src` and its tests is required to satisfy this design.

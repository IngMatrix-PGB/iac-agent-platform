# Batch 32 design — operator review surface

Status: closed. The six human decisions in section 16 are approved. This document is not an implementation plan and is not permission to change code.

Baseline: `origin/main` `d177047e5dcab785bbe4c7a8e4203759e960a629`, the merge of pull request 14. Reviewed Batch 31 head `8a178a45df4832106bf611de0cddc2ea59f8f3ed` is an ancestor of that commit.

## 1. Current system baseline after Batch 31

One local product. An operator writes a natural-language infrastructure request. A deterministic resolver maps a closed intent vocabulary onto an existing Terraform composition. The workflow plans, runs policy and Checkov, and stops for human approval. Approval resumes publication of a pull request. Terraform apply and destroy do not run.

The operator can do this in a browser. The React UI is built with Node and copied into the same Python image that serves FastAPI. Compose publishes only `127.0.0.1:8000:8000`. The API and UI are unauthenticated. The SQLite checkpoint on volume `iac-agent-state` is the durable record. The request id in the URL is the only client-side identity.

Supported end-to-end resource kinds are SQS, S3, DynamoDB, Lambda, API Gateway, and ECR. Intent capabilities are `http_endpoint`, `queue_processing`, `persistence`, `object_storage`, and `container_registry`. Compositions already include a queue, object storage, a table, a function, an HTTP API plus function, an HTTP API plus function plus table, a serverless worker, and an ECR repository. Golden evals exist for those slices. Langfuse is optional and off unless configured. The production lifespan still requires GitHub and OpenAI configuration before `python -m iac_agent.api` serves.

## 2. Architectural flow

```
Browser (same origin)
  composer on /
  durable page on /requests/{request_id}
        |
        | ApiClient only: POST /api/v1/requests
        |                 GET  /api/v1/requests/{request_id}
        |                 POST /api/v1/requests/{request_id}/approval
        |                 GET  /health
        |                 GET  /ready
        v
FastAPI
  project_submission / project_view  -> public RequestResponse
  SPA files only when IAC_AGENT_UI_DIST is set
  /api, /health, /ready stay JSON
        |
        v
IntentResolutionService
  interpreter -> ArchitectureIntent
  ArchitectureResolver -> resolved spec | clarification | unsupported
        |
        v
IacApplication + LangGraph
  render -> terraform plan -> policy -> checkov -> approval -> publish
        |
        v
SQLite checkpoint (authoritative)
Ephemeral workspace (not on the state volume)
Optional Langfuse (fail-open, default off)
```

The UI does not call the graph, Terraform, or GitHub. It renders the public DTO and posts approve or reject. The server decides whether that decision resumes, returns the current projection, or returns HTTP 409 with the current request embedded.

## 3. Current strengths

- The trust boundary is explicit: loopback publication, uid 10001, no Docker socket, no privileged mode, no host networking, no apply or destroy.
- HITL survives container replacement. The checkpoint, not the browser, is authoritative.
- The public projection is thin. Findings are policy id, status, and severity. Errors are stage and error type. A pull request is a URL only.
- The SPA fallback does not capture `/api`, `/health`, or `/ready`.
- The same container serves the UI and the API. Node is build-time only.
- Resource coverage and golden evals are already broader than a single queue demo.
- Approval requires confirmation. Reject does not. A conflict replaces the view with the server request. Polling is bounded.

## 4. Current limitations and technical debt

The operator UI is functionally complete and visually a single column of unlabeled paragraphs. `ui/src/styles.css` sets a system font, a 72rem column, a red banner border, and a short mobile padding rule. Plan counts are sequential paragraphs (`Add`, `1`, `Change`, `0`, `Destroy`, `0`). Workflow status, stage, security status, and approval availability are the same shape. Findings are a plain table. There is no page heading hierarchy beyond `IaC Agent Platform`, no status language an operator can scan, and no distinct treatment for a destructive plan, a blocked result, or an in-flight poll.

There is no list of durable requests. Recovery requires the request id in the URL or typed into "Open request". Clarification and unsupported results stay on `/` and are lost on refresh, which is intentional and easy to miss.

`python -m iac_agent.api` still refuses to start until GitHub and OpenAI configuration are present, even for a request that would not call them. That eager startup requirement is recorded in `docs/api.md`.

The roadmap's "not yet started" list is long: authentication, RBAC, tenants, public deployment, EventBridge, SNS, a second Lambda, composition chaining, Cognito, WAF, custom domains, a plugin registry, and DynamoDB actions beyond `PutItem`. None of those are implied by Batch 31.

## 5. Candidate Batch 32 vertical slices

### A. Operator UI review surface

Restyle and restructure the existing screens so an operator can scan the request, the plan counts, the findings, and the approval decision without reading raw status strings in document order.

- Operator value: high. This is the surface a reviewer actually sees.
- Architectural value: low. No new backend behavior.
- Portfolio value: high. Batch 31's function is hard to demonstrate in its current presentation.
- Security: low, if the batch renders only fields already on the public DTO and adds no bundle secrets.
- Complexity: moderate. Layout, states, and accessibility tests. No workflow change.
- Dependencies: none beyond the current UI and the existing Playwright fake.
- Vertical slice: yes, as the operator review experience. It does not add a backend capability.
- Invariants at risk: visual tests can start asserting copy that the server does not own; a "friendlier" status could invent a transition. Destructive emphasis could be mistaken for a new plan fact.

### B. Authentication and authorization

Add a caller identity and stop treating loopback as the only control.

- Operator value: none until more than one person uses the tool, or the port leaves the laptop.
- Architectural value: high, and it changes the trust boundary.
- Portfolio value: easy to over-claim. A local login is not production auth.
- Security: this is the security batch. A weak scheme would be worse than the current documented "unauthenticated local" boundary.
- Complexity: high. Tokens, session storage, UI login, Docker env, tests that must not bake secrets.
- Dependencies: a chosen identity source. None exists.
- Vertical slice: yes, but it is a boundary change, not a feature on the current product.
- Invariants at risk: loopback-only unauthenticated local use; replacement-container HITL if auth state is confused with the checkpoint; public exposure if someone treats auth as permission to bind beyond loopback.

### C. Durable request index

Add a read API that lists checkpointed requests and a UI that opens them without pasting an id.

- Operator value: high. Losing the URL currently loses the way back, even though SQLite still has the checkpoint.
- Architectural value: medium. It is a new read model over the checkpoint, not a new workflow.
- Portfolio value: medium. It makes the durable story visible.
- Security: medium. A list can leak ids and statuses to anyone who can open the port. It must not return checkpoint bodies, workspaces, or fields absent from the public projection.
- Complexity: medium. Query, pagination or a hard cap, empty state, and a decision about sort order. `RequestResponse` has no timestamp today.
- Dependencies: checkpoint enumeration that does not treat the id as a filesystem path.
- Vertical slice: yes.
- Invariants at risk: public DTO shape if the list adds fields; inventing `pending` for a missing row; scanning the SQLite directory unsafely.

### D. Another infrastructure capability

Add a resource or composition that the roadmap still lists as not started.

- Operator value: depends on the resource. The current set already covers queue, storage, table, function, HTTP API, worker, and registry.
- Architectural value: repeats a known pattern. The next items (EventBridge, SNS, chaining, authorizers) are larger than one resource contract.
- Portfolio value: diminishing until the existing slices are reviewable.
- Security: each new module, policy, and plan path can widen what Terraform sees. Apply must stay off.
- Complexity: high. Intent vocabulary, resolver, module, policy, evals, UI projection.
- Dependencies: a chosen resource and golden prompts.
- Vertical slice: yes, and it is the historical shape of this repository.
- Invariants at risk: closed capability enum, public projection, offline provider mirror, no apply/destroy.

### E. Runtime beyond local Docker

Deploy the container somewhere other than the operator's machine.

- Operator value: low until auth and a non-loopback story exist.
- Architectural value: high and premature.
- Portfolio value: high if overstated, low if honest.
- Security: unacceptable on the current unauthenticated API.
- Complexity: high.
- Dependencies: B, plus a host, secrets handling, and an explicit public-exposure decision.
- Vertical slice: not by itself. It would ship the current trust boundary into a new network.
- Invariants at risk: loopback publication, unauthenticated local use, no secrets in the image, uid 10001.

### F. Evaluation and observability

Expand golden sets or surface Langfuse in the product.

- Operator value: low for Langfuse. The operator does not need a trace UI to approve a plan.
- Architectural value: moderate. Evals already exist per resource. Langfuse is fail-open and off by default.
- Portfolio value: moderate, and easy to confuse with AWS monitoring.
- Security: traces can contain prompts and must not become a new public payload.
- Complexity: medium to high.
- Dependencies: real-model evals are already marked and must not become the default CI path.
- Vertical slice: a better eval is a quality increment, not an operator workflow.
- Invariants at risk: default-off telemetry, no secrets in the UI, no public DTO growth.

### G. Lifespan decoupling

Let the process serve `/health`, `/ready`, and the UI when GitHub or OpenAI configuration is absent, and fail only the call that needs them.

- Operator value: medium for local startup friction.
- Architectural value: medium. It removes recorded technical debt.
- Portfolio value: low. It is invisible when the happy path is configured.
- Security: low if missing credentials still fail closed on interpret and publish.
- Complexity: medium. The lifespan is shared by Docker acceptance, which today passes placeholder env.
- Dependencies: none.
- Vertical slice: no. It is hardening.
- Invariants at risk: Docker health tests that assume the holder exists only after those env vars are set; accidentally serving a half-open publisher.

## 6. Tradeoff analysis

| Candidate | Do it now? | Why |
| --- | --- | --- |
| A. Review surface | Yes | Uses the product that just shipped. Does not move the trust boundary. |
| B. Auth | No | Changes the local-unauthenticated contract. Needs its own approval. |
| C. Request index | Later | Real operator gap, but it is a new read API. The detail page should be readable first. |
| D. New resource | No | The platform is no longer a one-resource demo. Another resource does not fix the review surface. |
| E. Remote runtime | No | Requires auth and an explicit exposure decision. |
| F. Evals / Langfuse | No | Quality work, not the operator slice. |
| G. Lifespan | Defer | Worth doing, not the batch that should follow the UI. |

UI polish should be Batch 32 itself, not a side task inside auth, history, or a new resource. Those batches have their own invariants. Folding a visual redesign into them would hide regressions in both. History should stay a later batch so the list, if approved, opens a page that is already scannable.

## 7. Recommended Batch 32 scope

Batch 32 is the operator review surface.

In scope:

- Information hierarchy on `/` and `/requests/{request_id}`: one title, a short description of what the page is, labeled sections for the request, the workflow, the plan, findings, and approval.
- Composer: keep the current submit and open-request behavior. Make the unsaved clarification and unsupported results visually distinct from a durable request. Keep the exact API messages.
- Workflow: show `workflow_status`, stage, security status, and approval availability as labeled facts. Do not rename server enums into a second state machine.
- Plan counts: show add, change, and destroy as three labeled values. When `destructive_change_detected` is true, show the existing sentence with stronger emphasis. Do not show resource addresses.
- Findings: keep the table of policy id, status, and severity. Add a caption and column scope. Do not add message, resource, or source.
- Approval: keep confirmation for approve, immediate reject, disabled controls while in flight, and the server-returned body. Make the confirmation text the primary content of the dialog.
- Polling and recovery: keep the 5-second, 12-poll rule and the URL id. Show a quiet in-progress state while a pollable status is refreshing, and keep the Refresh button after the budget is exhausted.
- Empty, missing, and error states: keep `request_not_found`, the fixed network sentence, and "This request was not saved." Give them a consistent region and focus behavior.
- Layout: one column, readable from 320px wide through the current 72rem measure. No second product surface.
- Accessibility: headings in order, labeled controls, dialog name, table headers, visible focus, status text that is not color alone.
- Styling: stay on the hand-written stylesheet. No component library, no CSS framework, no new runtime dependency. Prefer a small set of custom properties for color, space, and type.

Approved presentation rules:

- The batch is presentation-only. It adds no HTTP route.
- It adds no public DTO field.
- A human-readable label may sit beside a server enum. The label must not replace, reinterpret, synthesize, or hide the authoritative server value. `awaiting_approval` stays visible even if the page also shows "Awaiting approval".
- The stylesheet stays hand-written. No component library.
- Request history and authentication stay outside this batch.
- Destructive emphasis must not rely on color alone. Keep the sentence "Destructive change detected." Typography, layout, and iconography may only supplement that sentence.

This document does not choose pixel values. The implementation plan may choose token names and section structure.

## 8. Explicit non-goals

- Authentication, RBAC, tenants, and public deployment.
- A request list or any new HTTP route.
- New public DTO fields.
- New infrastructure resources, compositions, or intent capabilities.
- Terraform apply or destroy.
- Langfuse UI, trace browsing, or enabling telemetry by default.
- Changing polling intervals, the 12-poll cap, or which statuses poll.
- Changing approve, reject, or 409 behavior.
- A second container, nginx, CORS, or a Node runtime process.
- Dark-mode themes, animation, and illustration.

## 9. Security and trust boundary

Batch 32 must not move the boundary Batch 31 documented.

- The UI remains unauthenticated and loopback-published.
- Components still talk to the API only through `ApiClient`.
- The browser still receives the public DTO only. No Terraform source, raw plan JSON, resource addresses, finding resource, finding message, finding source, `WorkflowError.message`, checkpoint bodies, workspace paths, or GitHub owner, repository, branch, or base branch.
- No build-time `VITE_` variable may carry a credential. The bundle stays static and same-origin.
- Visual emphasis is not a new fact. A destructive plan is still the boolean the server sent.
- The SPA fallback rules are unchanged.

If a design review wants a friendlier status label, the server enum must remain on the page. A label may sit beside it. The label must not be the only record of the state. This rule is approved: companion text may space and capitalize an enum, and the raw server value stays in the document. Color must not be the only signal that a plan is destructive.

## 10. Proposed architecture

No new server component. The React tree stays:

- `App` chooses compose, request, or unknown from the path.
- `ComposePage` submits and shows unsaved outcomes.
- `RequestPage` loads by id, polls when `shouldPoll` is true, and renders the projection plus `ApprovalPanel`.

Batch 32 changes presentation components and `styles.css`. It may split a section's markup so a heading, a definition list, or a table is accessible. It must not add a state library, a data-fetching library, or a second copy of the approval rules.

The Docker image picks up the new static files through the existing Node build stage. No Dockerfile behavior change is required unless the build output path changes, which it must not.

## 11. Expected production files

Likely:

- `ui/src/styles.css`
- `ui/src/pages/compose-page.tsx`
- `ui/src/pages/request-page.tsx`
- `ui/src/components/request-summary.tsx`
- `ui/src/components/workflow-status.tsx`
- `ui/src/components/plan-summary.tsx`
- `ui/src/components/findings.tsx`
- `ui/src/components/approval-panel.tsx`
- `ui/src/components/error-banner.tsx`
- `ui/src/components/health-indicator.tsx`
- `ui/src/components/request-form.tsx`
- `ui/src/components/open-request.tsx`
- `ui/src/app.tsx`

Not expected:

- `src/iac_agent/api/schemas.py`
- `src/iac_agent/api/routes.py`
- `src/iac_agent/api/project.py`
- workflow, approval, or checkpoint modules
- `Dockerfile` and `compose.yaml`, unless a later review finds the static path changed
- CI, except the existing Frontend job already builds the UI

`docs/api.md` should mention that the UI is a review surface over the same DTO, only if the visible copy changes a sentence an operator relies on. `docs/roadmap.md` gets updated when the batch is actually done, not in this design turn.

## 12. Expected tests

- Component tests for hierarchy: headings, plan labels, findings caption, destructive sentence, missing request, unsaved interpreter failure.
- Approval tests unchanged in behavior: confirm, cancel, reject, in-flight disable.
- Polling tests unchanged: 12 polls, no poll on `awaiting_approval`, timer cleanup.
- Playwright happy path and conflict path still pass, updated only where accessible names stay the same or gain an explicit accessible name that the test should use.
- `npm test`, `npm run build`, and `tsc --noEmit`.
- Deterministic pytest, to prove the backend did not move.
- No new Docker behavior. The existing UI image test still finds `IaC Agent Platform` in `index.html`.

## 13. Acceptance gates

1. An operator can identify the request id, outcome, plan counts, and approval availability without reading unlabeled paragraphs.
2. Approve still requires confirmation. Cancel still sends no mutation. Reject still sends immediately.
3. HTTP 409 still replaces the view with the embedded request.
4. Polling rules are unchanged.
5. Unknown ids still show `request_not_found` and do not invent a workflow.
6. The rendered DOM does not contain a finding message, a resource address, an ARN, or a workspace path supplied only as a hidden fixture.
7. Frontend unit tests, the production build, Playwright, and the deterministic Python suite pass.
8. `git diff` for the batch does not touch the public DTO or workflow semantics.

## 14. Risks

- Accessible-name changes can break Playwright and Testing Library queries. Update the tests in the same change that changes the name.
- A visual "status pill" can drift from `workflow_status`. Keep the server string.
- Emphasis on destroy counts can look like the UI decided the plan was dangerous. The boolean remains the server's.
- CSS that hides overflow can clip the confirmation sentence. The confirmation text stays fully visible.
- Scope can grow into a list view or a dashboard. That is a different batch.

## 15. Deferred work

- Durable request index (candidate C), after this surface is readable.
- Authentication and any non-loopback deployment (candidates B and E), as their own approved boundary change.
- New resources and compositions (candidate D).
- Langfuse or eval expansion (candidate F).
- Lifespan decoupling (candidate G).
- Request history, dark theme, and animation.

## 16. Human decisions

Approved for the implementation plan. Not a waiver of the stop conditions in that plan.

1. Approved. Batch 32 is presentation-only and adds no HTTP route.
2. Approved. No new public DTO field, including no list item and no timestamp.
3. Approved. Server workflow, status, and security enum values stay visible. Presentation may add a human-readable label or supporting text beside the value. It must not replace, reinterpret, synthesize, or hide the authoritative server value.
4. Approved. No component library. Use the existing React application and a hand-written stylesheet and design primitives.
5. Approved. Request history and authentication remain outside Batch 32.
6. Approved. Destructive-change emphasis must not rely on color alone. Preserve the existing semantic sentence and use typography, layout, or iconography only as supplementary presentation.

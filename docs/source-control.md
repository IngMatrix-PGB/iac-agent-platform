# Source-Control Publication

## The port boundary

`iac_agent.graph` depends only on `iac_agent.git.port.SourceControlPort`
— one high-level operation, `publish_change(...)`. The graph knows
nothing about Git object SHAs, the GitHub blob/tree/ref APIs, HTTP
status codes, or authorization headers; a dedicated architecture test
(`test_graph_module_does_not_contain_github_specific_details`)
confirms none of those strings appear anywhere in
`iac_agent.graph.workflow`. Everything GitHub-specific lives in the one
concrete implementation, `iac_agent.git.github.GitHubSourceControl`.

## The GitHub adapter

`GitHubSourceControl` implements `publish_change` using GitHub's Git
Data API — chosen over the Contents API specifically so every
generated file lands in **one** commit, not one commit per file:

```
GET  base branch ref/SHA           (also used to check target-branch collision)
GET  base commit -> base tree SHA
POST one blob per file
POST one tree (layered on the base tree, so nothing else in the
     repository is touched)
POST one commit (parent = the base commit)
POST the new branch ref
POST the pull request
```

Every endpoint, payload shape, and the `X-GitHub-Api-Version` header
value (`2026-03-10`) were verified directly against the current GitHub
REST API documentation before implementation — not assumed from an
older tutorial. HTTP is the Python standard library's `urllib` only; no
new runtime dependency (`requests`, `httpx`, `PyGithub`, `GitPython`)
was added, and the adapter never shells out to `git` or the `gh` CLI.

An injectable `HttpTransport` makes every adapter test deterministic
and network-free — production code uses `UrllibHttpTransport`, tests
inject a fake that returns canned responses. Zero test in this project
contacts `api.github.com`.

## APPROVED-only mutation

Source-control mutation is reachable only from `WorkflowStatus.APPROVED`.
`REJECTED`, `BLOCKED`, `ERROR`, `AWAITING_APPROVAL`, `RUNNING`, and
`PENDING` can never reach it — graph routing already restricts this
(only `approval_gate`'s APPROVED branch points at `source_control`), and
a defense-in-depth precondition inside the node itself
(`_ensure_workflow_approved`) refuses to call the adapter at all
otherwise, independent of routing.

## Deterministic branch naming

`iac_agent.domain.source_control.derive_branch_name(request_id)` always
returns `iac-agent/<request_id>` — no timestamp, no random UUID, no
caller-supplied ref syntax. The same `request_id` always derives the
same branch name. `request_id` must satisfy the existing
`validate_request_id` rule (shared with the workspace path resolver and
checkpoint thread-ID mapping) *and* a stricter Git-branch-safe pattern
(must start with a letter/digit; only letters, digits, `.`, `_`, `-`
afterward — no spaces, no `~^:?*[`, no leading hyphen).

## Generated-file destination and allowlist

Every published file lands at `generated/<request_id>/<relative_path>`
(`iac_agent.domain.source_control.resolve_generated_file_path`) —
deliberately distinct from the gitignored, local-only
`artifacts/<request_id>/` runtime workspace convention (see
`.gitignore` and `iac_agent.providers.aws.sqs.renderer`): `artifacts/`
is never source-controlled, so reusing that name for the committed
destination would be actively misleading.

The file mapping published is always exactly
`GeneratedTerraformComposition.files` (`state["generated_files"]`) —
currently `{"main.tf", "versions.tf"}` — passed explicitly to the port.
Nothing crawls the local workspace directory, so a `tfplan`, a
`.terraform/` directory, `terraform.tfstate`, the SQLite checkpoint
database, or raw Checkov/Terraform output can never be published: they
simply never appear in that mapping. `resolve_generated_file_path`
additionally rejects an empty, absolute, backslash-containing, or
`..`-containing relative path before ever building the final path.

## No local worktree mutation

The adapter never touches the developer's checked-out working tree —
no `git checkout`/`switch`/`add`/`commit` against the local repository.
Every mutation happens through the GitHub REST API against the
configured remote repository only.

## Conflict behavior — fail closed

If the target branch already exists, `publish_change` raises
`GitHubConflictError` (a `SourceControlConflictError`) *before* any
write happens (no blob, tree, or commit is created) — Phase 1 never
appends a random suffix, force-updates the branch, deletes it, or
overwrites it.

## No automatic retry

Exactly one attempt per `publish_change` call. A `429`/`5xx` response
is `GitHubApiError`, not a signal to retry — after a request that may
have already mutated the remote repository, the client cannot always
tell whether it succeeded before the response was lost, so an automatic
retry could double-create a branch/PR. Batch 14 fails closed
(`WorkflowStatus.ERROR`) instead of guessing.

## Idempotency / replay safety

LangGraph's checkpoint replay has a real hazard here, verified
empirically (not assumed) before this batch's design was finalized:
calling `graph.invoke(<same input>, config)` again on an
already-**PR_CREATED** thread re-runs the *entire* graph from `START`,
including `source_control`. Two independent layers make this safe:

1. **Graph-level guard**: `source_control` checks
   `state.get("pull_request")` first — if already set (from a prior
   successful publish on this thread), it returns that same result
   unchanged rather than calling the adapter again.
2. **Adapter-level guard**: branch naming is deterministic
   (`iac-agent/<request_id>`), and the adapter fails closed on an
   existing branch — so even if the graph-level guard were somehow
   bypassed, a second `publish_change` attempt for the same
   `request_id` would collide on the same branch name and raise
   `GitHubConflictError` rather than create a second PR.

`get_state()` alone never triggers a side effect, checked directly
(`test_replayed_invocation_of_a_published_thread_does_not_call_source_control_again`).

## The token never enters state

`GitHubSourceControl` receives its token only through its constructor,
stores it in a private attribute, and never places it in
`WorkflowState`, a `PullRequestResult`, a raised error message, its own
`__repr__`, a log line, or anything serialized to SQLite. The
composition layer (not the graph) is responsible for sourcing the
token — Batch 14 adds no hidden environment-variable read inside the
graph itself.

## PR_CREATED lifecycle meaning

`WorkflowStatus.APPROVED` is now an *intermediate* post-HITL status —
success at `source_control` sets `WorkflowStatus.PR_CREATED`, the Phase
1 terminal artifact. `PR_CREATED` means "the approved infrastructure
change is ready for review/merge," never "infrastructure deployed."

## No Terraform apply, ever

There remains no `terraform apply` or `terraform destroy` path
anywhere in this codebase (`TerraformRunner` still has no such method),
and no AWS mutation of any kind. Opening a pull request does not
deploy anything.

## Batch 14 uses mocked GitHub only

Every test in this batch injects a fake `HttpTransport` or a
test-only `SourceControlPort` fake — there is no live remote branch or
pull request created against any real GitHub repository, including the
project's own. A later, explicitly authorized live-smoke batch will
perform exactly one real PR.

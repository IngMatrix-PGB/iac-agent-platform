# Durable Workflow Persistence

## Why SQLite for Phase 1 checkpoint storage

Phase 1 needs the LangGraph workflow to survive process restarts —
after the process that ran `render_terraform → … → security_gate` for
a request exits, a later process must be able to recover exactly where
that request left off. SQLite is a single-file, dependency-free,
synchronous store that satisfies this with no separate database server
to run, configure, or secure — appropriate for a Phase 1 vertical
slice. It is deliberately not Postgres, Redis, or DynamoDB; those
remain future options behind the same boundary (see below), not
decisions made now.

## `request_id == thread_id`

LangGraph's durable state model keys everything by a `thread_id`. This
project never introduces a second identity: `request_id` (already the
stable identifier used for the request-specific Terraform workspace,
see `docs/terraform-credential-free-plan.md`-adjacent workspace
conventions) *is* the thread ID, with no separately generated UUID or
timestamp anywhere in between. `iac_agent.persistence.checkpoints.workflow_config(request_id)`
is the single place this mapping is made, returning
`{"configurable": {"thread_id": request_id}}`. `request_id` is
validated with the exact same rule used to resolve the request's
Terraform workspace path
(`iac_agent.domain.workflow.validate_request_id`) — one rule set, not
two that could quietly drift apart.

## Explicit database path — no default location

`iac_agent.persistence.checkpoints.open_sqlite_checkpointer(db_path)`
requires an explicit `Path`. There is no default such as `./state.db`,
`/tmp/state.db`, or `~/.iac-agent/state.db` — a caller always states
exactly where the checkpoint database lives. The path must not already
exist as a directory, and its parent directory must already exist;
Phase 1 deliberately rejects a missing parent rather than silently
creating one on the caller's behalf.

## Durable state survives graph reconstruction

`open_sqlite_checkpointer` is a context manager wrapping a real
`sqlite3.Connection` and a `SqliteSaver`. On exit, the connection is
always closed — no lingering open handle. A later process (or a later
test, simulating one) opens a brand-new connection and a brand-new
`SqliteSaver` against the *same* database file, compiles a brand-new
graph with `build_sqs_workflow(..., checkpointer=that_new_saver)`, and
calls `compiled_graph.get_state(workflow_config(request_id))` to
recover the exact same typed `WorkflowState` values — including the
`SQSResourceSpec`, `PlanSummary`, `PolicyEvaluation`,
`CheckovScanResult`, and `SecurityGateResult` domain objects, not
flattened dicts. This is proven both with fakes
(`tests/unit/graph/test_workflow.py`) and with the real Terraform and
Checkov binaries
(`tests/integration/test_sqs_workflow_persistence.py`).

## No unsafe pickle fallback

LangGraph's default `JsonPlusSerializer` will deserialize *any*
unregistered type it encounters, emitting a deprecation warning each
time. Rather than rely on that permissive default, this project
constructs the serializer with an explicit `allowed_msgpack_modules`
allowlist naming exactly this project's own domain types (every
`SQSResourceSpec`/`EncryptionSpec`/`DlqSpec`, every `PlanSummary`/
`ResourceChange`/`PlanAction`, every security/policy/workflow model).
Nothing outside that list is deserialized. `pickle_fallback` is never
set to `True` anywhere in this project.

## What is intentionally NOT checkpointed

Batch 12 also corrected a pre-existing gap: `WorkflowState` has no raw
Terraform `show -json` field of any kind (there is no
`terraform_plan_json` key, not even one that gets cleared later).
`plan_analysis` calls `terraform_runner.show_json(...)`, holds the
result in a local Python variable, derives `PlanSummary` from it via
`analyze_plan`, and returns only the `PlanSummary` as a state update.
The raw plan dictionary is never assigned into `WorkflowState`, so it
can never be written into a SQLite checkpoint, no matter what future
node ordering or error path exists. The same reasoning already applied
to Checkov (Batch 8): only normalized `SecurityFinding` values and
aggregate counts are ever state-shaped, never raw scanner JSON.

## No human-in-the-loop yet

Batch 12 proves persistence only — write a checkpoint, recover the
current state. It adds no `interrupt()`, no `Command(resume=...)`, no
approval fields. Durable HITL (pausing a workflow for a human decision
and resuming it later, potentially in a different process) is Batch
13's concern, built on top of the durability this batch establishes.

## The persistence adapter boundary

`iac_agent.persistence` is the only package in this project that
imports `sqlite3` or `langgraph.checkpoint.sqlite`. `iac_agent.graph`
depends only on the generic, backend-agnostic `BaseCheckpointSaver`
abstraction — `build_sqs_workflow(..., checkpointer=None)` (the
default) preserves Batch 11's exact non-durable behavior, and
`build_sqs_workflow(..., checkpointer=<any BaseCheckpointSaver>)`
enables durability, without the graph module ever constructing a
SQLite connection itself. `iac_agent.domain`, `iac_agent.providers`,
`iac_agent.security`, and `iac_agent.policies` never import from
`iac_agent.persistence` or from SQLite-specific modules at all —
verified by a dedicated test.

A future backend (Postgres, for example) would only need its own
`open_<backend>_checkpointer(...)`-shaped factory returning a
`BaseCheckpointSaver`; nothing in `iac_agent.graph` would need to
change to accept it.

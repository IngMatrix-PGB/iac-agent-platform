# Human-in-the-Loop Approval Gate

## The security gate precedes the human gate

The deterministic pipeline (contract validation → Terraform plan →
plan analysis → platform policy → Checkov → security gate) always runs
to completion first, exactly as built in Batches 4-9. Human review is
an additional gate layered *after* that deterministic evidence exists —
never a substitute for it, and never evaluated before it.

## PASS and WARN require review; BLOCK and ERROR cannot reach approval

```
security_gate
   |
   +-- BLOCK --> WorkflowStatus.BLOCKED --> END   (no interrupt, ever)
   |
   +-- PASS ----+
   |            |
   +-- WARN ----+
                |
                v
          approval_gate
                |
           interrupt(payload)
                |
          durable checkpoint
                |
          resume(APPROVE | REJECT)
          /                      \
     APPROVED                  REJECTED
```

If any deterministic stage before `security_gate` raises (a Terraform,
plan-analysis, Checkov, or security-gate boundary error),
`WorkflowStatus.ERROR` is set and the graph routes straight to `END` —
the existing Batch 11 fail-stop behavior, unchanged. Like `BLOCK`, an
`ERROR` workflow never reaches `approval_gate`; there is no code path
in `iac_agent.graph.workflow` where the `approval_gate` node can run
except when `security_gate` has already set `WorkflowStatus.AWAITING_APPROVAL`.

This is proven structurally, not just by convention: a `BLOCK` or
`ERROR` thread's checkpoint has an empty `next` (no pending tasks) —
there is nothing for a later `Command(resume=...)` call to resume. An
attempted approval resume against such a thread is a no-op; the
thread's `workflow_status` never becomes `APPROVED` (see
`tests/unit/graph/test_workflow.py::test_block_thread_cannot_be_approved`
and `::test_error_thread_cannot_be_approved`).

## Human approval cannot override a deterministic block

This is the central Batch 13 rule. There is no code path — no
override flag, no elevated-approval concept, no "force approve" —
that can turn a `BLOCK` or `ERROR` thread into `APPROVED`. The only two
outcomes reachable from `AWAITING_APPROVAL` are `APPROVED` and
`REJECTED`, and `AWAITING_APPROVAL` is only ever reached from a `PASS`
or `WARN` security result.

## SQLite makes interruption durable

`approval_gate` calls LangGraph's `interrupt()`, which requires a
checkpointer to be resumable at all — calling
`Command(resume=...)` against a graph compiled with `checkpointer=None`
raises `RuntimeError`. This project's only checkpointer is the SQLite
adapter from Batch 12 (`iac_agent.persistence.checkpoints`); nothing
new was introduced for durability in Batch 13. A workflow paused at
`approval_gate` survives process restarts exactly like any other
checkpointed state: a new `SqliteSaver` opened against the same
database file, feeding a newly compiled graph, recovers the exact same
`AWAITING_APPROVAL` state and can be resumed from there.

`request_id == thread_id` continues to hold exactly as established in
Batch 12 (`iac_agent.persistence.checkpoints.workflow_config`) — no
second approval-specific identifier was introduced.

## The approval payload is bounded and derived, never raw

`interrupt()` is called with a small, JSON-shaped dict built only from
already-derived, already-normalized evidence:

```json
{
    "request_id": "req-001",
    "resource": "order-events",
    "security_status": "pass",
    "plan": {"add": 2, "change": 0, "destroy": 0},
    "findings": [
        {"policy_id": "...", "status": "...", "severity": "...", "resource": "..."}
    ]
}
```

It never contains raw Terraform `show -json` output, raw Checkov JSON,
subprocess stdout/stderr, credentials, environment variables, exception
objects, or filesystem paths — the reviewer sees exactly the same
normalized `PlanSummary`/`SecurityGateResult` evidence already proven
safe in Batches 6-9. A `WARN` security result is surfaced as
`"security_status": "warn"` — it is never silently normalized to
`"pass"`.

## No reviewer identity yet

`ApprovalDecision` is deliberately a bare two-valued enum
(`APPROVE`/`REJECT`) with no `approved_by`, `reviewer`, `user_id`,
`email`, `comment`, or timestamp field. Batch 13 has no authenticated
caller identity source (no FastAPI, no auth) — storing an unverifiable
identity string would create a false impression of audit trust. A
future batch may add reviewer identity once a verified principal exists
upstream of this graph.

An invalid resume value (anything other than the exact strings
`"approve"`/`"reject"` — a synonym, a boolean, an integer, a mapping) is
rejected by `iac_agent.domain.approval.parse_approval_decision` and
turned into `WorkflowStatus.ERROR`, the same fail-closed treatment as
every other boundary error in this graph. It is never interpreted as
`APPROVE`.

## APPROVED does not mean deployed

`WorkflowStatus.APPROVED` means "eligible for the next deterministic
source-control stage" — nothing more. There remains no `terraform
apply` path anywhere in this codebase (`TerraformRunner` has no such
method), and approval triggers no Terraform mutation. GitHub
source-control mutation (branch/commit/PR) is Batch 14's concern, not
this one.

## REJECTED is a normal terminal outcome

A human `REJECT` sets `WorkflowStatus.REJECTED` and
`WorkflowStage.COMPLETE` — it is not `ERROR` (no boundary failure
occurred) and not `BLOCKED` (security evidence never rejected the
change; a human did). The underlying `SecurityGateResult` is completely
unchanged by rejection, exactly as it is by approval.

## Security evidence is never rewritten by approval

`SecurityGateResult` has no mutation path in this codebase (see
`iac_agent.domain.security`) and `approval_gate` never constructs a new
one. A `WARN` result before approval is inspectable as
`security_gate.overall_status == WARN` after the workflow reaches
`APPROVED` — human review only ever adds `workflow_status` and
`approval_decision`, never a rewritten security outcome.

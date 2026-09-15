# Serverless Worker Composition: SQS -> Lambda -> DynamoDB (Phase 2, Batch 19)

## Why this composition, and why this document exists

Batches 16-18 proved the platform generalizes across independent,
single-resource AWS types (S3, DynamoDB, Lambda+its execution IAM).
Batch 19 proves a different kind of generalization: that the platform
can represent a small, deterministic **multi-resource architecture** —
an SQS queue, a Lambda consumer, and a DynamoDB table, bound together
by an event source mapping and two narrowly-scoped IAM policies — as
**one** top-level request, without becoming an arbitrary graph DSL, a
generic workflow engine, a generic IAM generator, or a generic
Terraform module composer. See `docs/roadmap.md` for the exact
registration touchpoints this batch used.

## Architecture

```
SQS queue  ---(event source mapping)--->  Lambda consumer  ---(PutItem)--->  DynamoDB table
```

Messages published to the queue trigger the Lambda function; the
function is granted permission to consume from that queue and to write
items to that table — nothing else. The trusted fixture package this
platform already uses for every Lambda request (see
`docs/resources/lambda.md`) does not actually process SQS messages or
write to DynamoDB — Batch 19 validates infrastructure composition, not
a sample business application.

## Composition contract: `ServerlessWorkerSpec`

`iac_agent.compositions.serverless_worker.contract.ServerlessWorkerSpec`
is the platform's first *composition* spec:

```python
ServerlessWorkerSpec(
    name: str,
    environment: str | None = None,
    queue: SQSResourceSpec,
    function: LambdaResourceSpec,
    table: DynamoDBResourceSpec,
    event_source_batch_size: int = 10,
    event_source_maximum_batching_window_seconds: int | None = None,
    tags: dict[str, str] = {},
)
```

`queue`, `function`, and `table` are exactly the existing
`SQSResourceSpec`/`LambdaResourceSpec`/`DynamoDBResourceSpec` — their
field definitions are never duplicated, and Pydantic's own field typing
(not a hand-rolled `isinstance` check) is what guarantees "the queue is
really SQS, the function is really Lambda, the table is really
DynamoDB." This is deliberately **not** a generic node/edge graph, not
a YAML DAG schema, and not a `resources: list[dict[str, Any]]` — the
architecture itself is fixed and named.

## Resource identity vs. architecture identity

`ResourceType` (`iac_agent.domain.resource`) still classifies only
actual AWS resource types — there is no `ResourceType.SERVERLESS`, and
none is planned. A separate `CompositionType`
(`iac_agent.domain.composition`) classifies architectures instead, with
exactly one member so far: `CompositionType.SQS_LAMBDA_DYNAMODB`. This
keeps the two identities cleanly separate: a request is dispatched by
resource type when it is one AWS resource, and by composition type when
it is a named architecture — never both, never a conflated third enum.

## Cross-resource invariants

Beyond Pydantic's structural type enforcement, `ServerlessWorkerSpec`
adds:

- **Pairwise-distinct identifiers.** `queue.name`, `function.name`, and
  `table.name` must all differ. This platform never silently renames a
  user-supplied resource to force uniqueness ("no shared-name
  guessing") — construction fails closed instead.
- **Environment consistency.** If the composition itself declares an
  `environment`, any sub-spec that also declares one must agree with
  it; a silent mismatch would hide a real authoring mistake.
- **Event-source batch size bounds**, verified against current AWS
  Lambda documentation ("Lambda parameters for Amazon SQS event source
  mappings"): 1-10,000 for a standard queue, 1-10 for a FIFO queue.
- **Event-source batching window bounds**: 0-300 seconds for a standard
  queue, and rejected entirely for a FIFO queue (Lambda's own
  documented "batching window is not supported for FIFO queues").

## Relationship 1: SQS -> Lambda (event source mapping)

The composition renderer emits exactly one
`aws_lambda_event_source_mapping`, referencing `module.queue.queue_arn`
and `module.function.function_name` — never a hardcoded or
string-built ARN. Configurable fields: `batch_size` (default 10) and
the optional `maximum_batching_window_in_seconds`. Partial-batch-
response behavior (`FunctionResponseTypes`/`ReportBatchItemFailures`)
is an explicit non-goal this batch.

### Lambda's SQS-consumer permissions

Verified directly against the real, published JSON of the
`AWSLambdaSQSQueueExecutionRole` AWS managed policy (never attached —
this platform never attaches AWS-managed policies to a generated
role):

```json
{
  "Action": [
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:GetQueueAttributes"
  ],
  "Resource": "*"
}
```

The composition renders the same three actions as a narrow **inline**
policy (`aws_iam_role_policy.sqs_consumer`), scoped to
`module.queue.queue_arn` only — never `Resource: "*"`.
`sqs:ChangeMessageVisibility` is deliberately excluded: it is not part
of this documented required permission set.

## Relationship 2: Lambda -> DynamoDB (write scope)

Batch 19 supports exactly one DynamoDB interaction: `dynamodb:PutItem`,
granted via a second narrow inline policy
(`aws_iam_role_policy.dynamodb_write`), scoped to
`module.table.table_arn` only. `UpdateItem`, `Scan`, `Query`,
`BatchWriteItem`, and `DeleteItem` are all explicit non-goals — none of
this composition's fields can cause a broader action to be granted.

## IAM design: Option B, not a Lambda-module change

Batch 19 evaluated two IAM implementation strategies:

- **Option A** — extend the trusted Lambda module with explicit
  optional inputs (`sqs_consumer_arns`, `dynamodb_write_table_arns`).
- **Option B** — have the composition layer create narrowly-scoped
  extra `aws_iam_role_policy` resources targeting the Lambda module's
  own execution-role output.

**Option B was chosen.** It keeps the Lambda module's own standalone
behavior completely unchanged (Batch 18's invariant — the module owns
only its own baseline CloudWatch Logs permissions), keeps permissions
fully deterministic (derived only from the composition's own typed
relationships, never from arbitrary caller-supplied actions/resources),
and never turns the Lambda module into generic IAM machinery aware of
SQS or DynamoDB. The only Lambda-module change this batch made at all
is a new output, `execution_role_name` (`aws_iam_role.this.id`) — the
smallest possible addition, exposing exactly the one value the
composition layer needs to attach its own policies to the right role.

There is still no `ResourceType.IAM`, and Batch 19 found no concrete
blocker that would require adding one.

## No generic IAM policy DSL

Nothing in this batch introduces `permissions: list[PermissionSpec]`,
`actions: list[str]`, or `resources: list[str]` anywhere in the public
contract. The two action lists
(`_SQS_CONSUMER_ACTIONS`/`_DYNAMODB_WRITE_ACTIONS`) are fixed,
checked-in constants in
`iac_agent.compositions.serverless_worker.renderer` — not a
caller-configurable field.

## Trusted module reuse

The renderer instantiates the three already-existing trusted modules
side by side — `module "queue"` (`terraform/modules/sqs`),
`module "function"` (`terraform/modules/lambda`), and
`module "table"` (`terraform/modules/dynamodb`) — and adds only the
relationship resources not naturally owned by any one of them
(`aws_lambda_event_source_mapping`, the two `aws_iam_role_policy`
resources, and their two `aws_iam_policy_document` data sources). No
resource implementation is ever duplicated; no serverless-specific copy
of any trusted module was created.

### Module outputs added

- **Lambda**: `execution_role_name` (new this batch — see "IAM design"
  above).
- **SQS**: none — `queue_url` was already exposed (Batch 3/4).
- **DynamoDB**: none — `table_name`/`table_arn` were already exposed
  (Batch 17) and are sufficient.

## Environment variable references

The Lambda module's `environment_variables` input becomes
`merge(<user-supplied literal map>, { QUEUE_URL = module.queue.queue_url,
TABLE_NAME = module.table.table_name })` — a real `merge()` call
(rather than a precomputed literal map) specifically because
`QUEUE_URL`/`TABLE_NAME` are genuine Terraform-only-known references,
unlike tags (see below), which are plain Python strings and are merged
directly in Python instead. Both are non-secret, name/URL-only values —
never an ARN where a name/URL suffices, and never a secret.

## Composition-level tags

`ServerlessWorkerSpec.tags` is merged into each constituent module's own
`tags` argument (the sub-resource's own tag wins on a key collision) —
a shared, architecture-level tag baseline layered under each resource's
more specific tags, computed directly in Python (never a Terraform
`merge()` call, since both sides are already-known literal values).

## Checkov profile

A composition's Checkov profile is **not** an automatic union of its
constituent resources' approved skip lists — that would trust an
assumption never actually verified for the composition itself. Instead,
a real, **strict** (zero-skip) Checkov scan was run first against the
composition's own rendered secure baseline:

- Real scan result: 10 managed resources, 69 passed, 6 failed.
- The six failed checks are **exactly** the union of DynamoDB's one
  already-approved skip (`CKV_AWS_119`) and Lambda's five
  already-approved skips (`CKV_AWS_117`, `CKV_AWS_116`, `CKV_AWS_158`,
  `CKV_AWS_173`, `CKV_AWS_272`) — no new finding appeared, and, proven
  explicitly, **no S3-related check appeared at all** (this composition
  never uses S3).

Because the union hypothesis was verified empirically rather than
assumed, no new `AskUserQuestion` decision gate was needed this batch —
`iac_agent.security.composition_checkov_profiles.
composition_checkov_profile_for(CompositionType.SQS_LAMBDA_DYNAMODB)`
is a direct, checked carry-forward of decisions already explicitly
approved by the project owner in Batches 17 and 18.

## Composition security policies

`iac_agent.policies.composition.evaluate_composition_policies` runs:

| Policy ID | Outcome | Evidence source |
|---|---|---|
| `SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED` | always PASS | the validated spec itself (Pydantic already guarantees both sub-specs exist and are correctly typed) |
| `SERVERLESS_DDB_WRITE_SCOPE_REQUIRED` | always PASS | the validated spec plus the renderer's fixed, non-configurable PutItem-only action choice |
| `SERVERLESS_NO_WILDCARD_IAM` | always PASS, evidence-only | the renderer's checked-in, reviewed action lists and scoping, proven against a real plan in `tests/integration/test_serverless_worker_renderer_terraform.py` |
| `TF_NO_DESTRUCTIVE_CHANGES` | shared with every other resource/composition type | the rendered `PlanSummary` |

In addition, the dispatcher re-runs the **constituent** Lambda/DynamoDB
sub-specs' own already-approved recommendation policies —
`LAMBDA_TRACING_RECOMMENDED`, `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED`,
`DDB_PITR_RECOMMENDED`, and `DDB_DELETION_PROTECTION_RECOMMENDED`
(reused verbatim from `iac_agent.policies.platform`, never
re-implemented) — against `spec.function`/`spec.table`. A composition's
Lambda tracing mode or DynamoDB point-in-time-recovery setting is
exactly as real a risk signal inside a composition as it is for a
standalone Lambda/DynamoDB request; dropping it here would silently
discard evidence Batches 17-18 already established matters. The SQS
queue's own DLQ/encryption policies are deliberately **not** re-run:
the composition only cares that the queue exists and is bound correctly
(`SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED`), and SQS's encryption
invariant is unconditional (never representable as disabled), so
re-running it would only repeat an unchangeable PASS.

There is deliberately **no separate IAM platform policy** here either —
the same reasoning as Lambda's own standalone contract: the two
composition-owned IAM policies' safety is a trusted-renderer invariant
and a Checkov concern, not something this typed-input layer
re-evaluates from scratch.

### Policy boundary: what plan-time evidence can and cannot support

Both composition-owned IAM policy documents reference a not-yet-created
resource's ARN (`module.queue.queue_arn` / `module.table.table_arn`), so
their `resources` field is genuinely **unknown** even in a
credential-free plan — verified empirically (`after_unknown` in a real
plan), exactly like Batch 18's identical discovery for the Lambda
module's own logs policy. `evaluate_composition_policies` never
pretends otherwise: it does not parse or re-derive that JSON. The
concrete resource-scoping expressions are instead verified via a
direct, justified static read of the renderer's own checked-in source,
and the full picture (known actions + unknown-but-present resource
reference + the static scoping expression) is proven together in
`tests/integration/test_serverless_worker_renderer_terraform.py`.

## Request-level dispatch: `IacRequestSpec` / `IacRenderer`

Before Batch 19, every request was assumed to be exactly one
`AWSResourceSpec`. `iac_agent.request.IacRequestSpec` widens this to
`AWSResourceSpec | ServerlessWorkerSpec`, and `iac_agent.request.
IacRenderer` is the new request-level rendering dispatch: `AWSResourceSpec
-> AWSResourceRenderer` (completely unchanged), `ServerlessWorkerSpec ->
ServerlessWorkerTerraformRenderer` (new). `IacRenderer` computes
whichever module-source shape each concrete renderer expects from the
same `ResourceType`-keyed `trusted_module_dirs` mapping every AWS
resource type already used — no new `CompositionType`-keyed trusted-
module-directory mapping was needed, because a composition's three
sub-resources are already registered there individually.

## Workflow integration

`iac_agent.graph.workflow.build_iac_workflow` is still the one shared
entry point. No new graph node: `render_terraform`, `platform_policy`,
and `checkov_scan` each gained one `match`/`case` branch (composition
vs. single resource); `terraform_execute`, `plan_analysis`, and
`approval_gate` needed **no** change at all, since none of them ever
inspected the request spec's type. `security_gate` gained a branch too,
via `evaluate_security_gate`'s new `required_policy_ids` parameter
(pointing at `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE`)
rather than a second, parallel gate function.

`resource_spec` (the `WorkflowState` field) is **not** renamed to
`request_spec`: only its declared type widened, to `IacRequestSpec`.
Every graph node, every existing test, and the application layer
already spell it `resource_spec`; a composition spec still has exactly
the shape every reader needs (a `.name` attribute, and a type
dispatchable by `match`/`case`). Renaming would have meant rewriting
dozens of existing call sites for a naming-only benefit — cosmetic
churn, not a fix for an actual mismatch — so it was not done.

## Source control

`source_control`'s PR/commit text branches on the request kind:

```
feat(iac): add serverless worker proposal <request_id>
```

and the PR body states the composition type plus its queue/function/
table names instead of a single "Resource type:"/"Resource:" pair —
never a raw Terraform dump either way:

```
Request ID: <request_id>
Composition type: sqs_lambda_dynamodb
Queue: <queue name>
Lambda: <function name>
DynamoDB: <table name>
Security status: <pass|warn>
Plan: 10 to add, 0 to change, 0 to destroy
Human approval: approved
```

## HITL

No semantic change: a clean PASS/WARN composition still pauses at
`AWAITING_APPROVAL`; a BLOCK result (a Checkov failure, or a
destructive plan) still terminates at `BLOCKED` with no interrupt ever
reached, exactly as for every AWS resource type.

## Application layer

`iac_agent.app.service.Phase1Application` is renamed to
`IacApplication` (with `Phase1Application` kept as a zero-cost
backward-compatible alias, mirroring `build_sqs_workflow` alongside
`build_iac_workflow`); `submit`'s type hint widens to `IacRequestSpec`.
`iac_agent.app.composition.open_application` needed **zero** changes:
its compiled graph already builds via the fully request-generalized
`build_iac_workflow`, so it already accepts a `ServerlessWorkerSpec`
today. Proven directly, not just asserted, by
`tests/integration/test_application_composition.py::
test_composition_request_works_through_the_existing_application_root` —
the same composition root, same real Terraform/Checkov, same fake
GitHub transport pattern as every other test in that file.

## Persistence

`ServerlessWorkerSpec` round-trips through the SQLite checkpointer with
no pickle fallback, exactly like every other spec type — proven via a
close/reopen/reconstruct cycle (new saver, new compiled graph, same
database file) in
`tests/integration/test_serverless_worker_workflow_persistence.py`.

## Explicit non-goals (this batch)

- API Gateway, EventBridge, SNS (Batch 20+).
- A second Lambda (producer/consumer split).
- Any expansion of SQS's existing DLQ behavior, or a Lambda-side DLQ/
  destination configuration.
- S3 as part of this composition.
- A generic IAM top-level resource type, a generic IAM policy DSL, or
  an arbitrary node/edge composition schema.
- Partial-batch-response event source behavior.
- `terraform apply`/`destroy` — still never present anywhere in this
  codebase.

## No `terraform apply`, still

Nothing about composition support changes this project's central
safety property: `TerraformRunner` has no `apply` method anywhere, no
AWS mutation of any kind ever occurs, and a GitHub pull request remains
the terminal artifact for a composition request exactly as it is for
every single AWS resource type.

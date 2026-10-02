# API Gateway → Lambda → DynamoDB Composition (Batch 26)

## Why this composition, and why this document exists

Batches 19 and 20 proved the composition architecture generalizes past
one member (`sqs_lambda_dynamodb`, then `api_gateway_lambda`). Batch 26
adds a **third** composition — a synchronous REST API backed by one
DynamoDB table — following the exact same pattern: a new typed
composition spec, a deterministic renderer reusing existing trusted
modules, composition-specific policies, a dispatch-registration entry
in each of the ~11 sites the design/plan enumerated, and no redesign of
any core layer.

The resolver already had a coherent combination for this:
`WorkloadType.API` + `SYNCHRONOUS` +
`{Capability.HTTP_ENDPOINT, Capability.PERSISTENCE}`. No new
`ArchitectureIntent` field was required. See `docs/intent.md`.

## Architecture

```
API Gateway HTTP API --(proxy integration + one explicit route)--> Lambda --(dynamodb:PutItem, this table only)--> DynamoDB
```

Reuses all three existing trusted modules (`terraform/modules/
api_gateway`, `terraform/modules/lambda`, `terraform/modules/
dynamodb`) unchanged — no new Terraform module was needed.

## The composition contract: `ApiLambdaDynamoDbSpec`

```python
ApiLambdaDynamoDbSpec(
    name: str,
    environment: str | None = None,
    api: ApiGatewayResourceSpec,
    function: LambdaResourceSpec,
    route: RouteSpec,
    table: DynamoDBResourceSpec,
    tags: dict[str, str] = {},
)
```

`RouteSpec`/`HttpMethod` are **reused verbatim** from
`iac_agent.compositions.api_lambda.contract` — not duplicated. This is
the one place a composition imports from a sibling composition rather
than only from `providers.aws.*`; `RouteSpec` is a pure,
dependency-free domain type, so this creates no cycle and no coupling
between the two renderers/policy modules.

**Deliberately not a subclass of `ApiLambdaSpec`, and does not extend
it.** This is the single most important design decision in this batch:
a structurally distinct type is what mechanically guarantees no
existing `isinstance(spec, ApiLambdaSpec)` or `case ApiLambdaSpec():`
dispatch site can ever silently classify this composition as the
older, table-less one. Proven directly by two dedicated tests
(`not issubclass`, `not isinstance`), not just asserted.

Cross-resource invariants extend `ApiLambdaSpec`'s pairwise-distinct
check from 2 to 3 names (`api`/`function`/`table`), and its
environment-consistency check to the third sub-spec — the same pattern
`ServerlessWorkerSpec` already established for its own three
sub-specs.

## Resolver defaults (closed decisions, not caller-configurable)

- **Exactly one fixed route**, reusing `API_LAMBDA_DEFAULT_ROUTE`
  (`POST /invoke`) — the same resolver-owned default `ApiLambdaSpec`
  uses. Multi-route support is explicitly out of scope for this batch.
- **Exactly one fixed DynamoDB partition key**, reusing
  `WORKER_DDB_DEFAULT_PARTITION_KEY` (`id`, string) — the same default
  `ServerlessWorkerSpec` uses.

## Lambda → DynamoDB IAM: exactly `dynamodb:PutItem`, never broader

Mirrors `ServerlessWorkerSpec`'s "Option B" IAM pattern exactly: one
composition-owned `aws_iam_role_policy`, attached via `role =
module.function.execution_role_name` (the trusted Lambda module's
existing output — no change to `terraform/modules/lambda`), scoped to
exactly the new table's ARN.

**Closed decision:** the granted action set is exactly
`("dynamodb:PutItem",)` — never `GetItem`, `UpdateItem`, `DeleteItem`,
`Query`, `Scan`, `BatchWriteItem`, or a wildcard. `ArchitectureIntent`
has no field distinguishing "read" from "write" persistence need, and
this project's established discipline is to grant the single narrowest
action a fixed, non-caller-configurable relationship can honestly
justify. Any additional DynamoDB behavior (read access, updates,
deletes) requires a future, separate, explicit architecture decision —
never added preventively.

## API Gateway integration / route / Lambda permission

Identical technique and fixed constants to `ApiLambdaSpec`'s own
renderer (`AWS_PROXY` integration, `payload_format_version = "2.0"`,
`apigateway.amazonaws.com` principal, execute-api ARN scoping) — not
repeated here; see `docs/compositions/api-lambda.md`.

## Composition policies

`iac_agent.policies.composition.evaluate_composition_policies` runs:

| Policy ID | Outcome | Evidence source |
|---|---|---|
| `API_LAMBDA_DYNAMODB_INVOKE_PERMISSION_REQUIRED` | always PASS | renderer's fixed invocation-permission emission |
| `API_LAMBDA_DYNAMODB_NO_WILDCARD_PRINCIPAL` | always PASS, evidence-only | renderer's fixed principal/action constants |
| `API_LAMBDA_DYNAMODB_ROUTE_EXPLICIT` | always PASS | `route` is a required field |
| `API_LAMBDA_DYNAMODB_WRITE_SCOPE_REQUIRED` | always PASS | renderer's fixed, single `dynamodb:PutItem` grant, scoped to this table only |
| `API_LAMBDA_DYNAMODB_NO_WILDCARD_IAM` | always PASS, evidence-only | trusted-renderer invariant, no field could cause a wildcard |
| `LAMBDA_TRACING_RECOMMENDED` | PASS/WARN, reused verbatim | the function sub-spec's own tracing mode |
| `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED` | PASS/WARN, reused verbatim | the function sub-spec's own reserved-concurrency setting |
| `DDB_PITR_RECOMMENDED` | PASS/WARN, reused verbatim | the table sub-spec's own point-in-time-recovery setting |
| `DDB_DELETION_PROTECTION_RECOMMENDED` | PASS/WARN, reused verbatim | the table sub-spec's own deletion-protection setting |
| `TF_NO_DESTRUCTIVE_CHANGES` | shared with every other resource/composition type | the rendered `PlanSummary` |

## Checkov

`composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA_DYNAMODB)`
returns a frozen profile. The skipped checks are `CKV_AWS_76`,
`CKV_AWS_116`, `CKV_AWS_117`, `CKV_AWS_119`, `CKV_AWS_158`,
`CKV_AWS_173`, `CKV_AWS_272`, and `CKV_AWS_309`. A missing composition
profile raises `ValueError`. The registration test expects this
profile to exist.

## HITL, presentation, and durability

- **PR body**: states composition type, API, route, Lambda, and table
  names — never a raw Terraform dump.
- **Commit message**: `feat(iac): add api lambda dynamodb proposal
  <request_id>` (`resource_kind = "api lambda dynamodb"`, matching
  `"serverless worker"`'s lowercase-with-spaces style).
- **CLI**: `architecture: API Gateway + Lambda + DynamoDB` — a
  human-readable label, deliberately different in format from the two
  existing snake_case labels (an explicit, one-off choice for this
  composition only; the other two are unchanged).
- **Durable HITL resume**: `ApiLambdaDynamoDbSpec` is registered in the
  checkpoint serializer's allowlist
  (`iac_agent.persistence.checkpoints._ALLOWED_WORKFLOW_TYPES`) — an
  easy-to-miss, critical dispatch boundary: an omitted entry does not
  raise at submit time, it silently degrades the spec into a raw
  `dict` on the next checkpoint load. Proven both in isolation (a
  direct `JsonPlusSerializer` round-trip) and end-to-end through a
  fresh-process reconstruction and resume.

## Dispatch sites touched

`domain/composition.py` (new `CompositionType` member) ·
`compositions/api_lambda_dynamodb/{contract,renderer}.py` (new) ·
`compositions/resource.py` (`CompositionSpec` union,
`composition_type_of`) · `request.py` (`IacRequestSpec` union,
`IacRenderer`) · `intent/resolver.py` (two new `match` arms) ·
`persistence/checkpoints.py` (allowlist entry) ·
`policies/composition.py` (policy IDs, dispatch arm) ·
`security/composition_checkov_profiles.py` ·
`graph/workflow.py` (PR body, commit message, three grouped dispatch
arms widened, `build_iac_workflow` renderer parameter) ·
`cli/present.py` (`_architecture_label`, `_component_lines`).

## Explicit non-goals (this batch)

- Multi-route support — exactly one fixed route, matching
  `ApiLambdaSpec` exactly.
- Any DynamoDB action beyond `PutItem` — read access, updates, and
  deletes are all explicit non-goals pending a future, separate
  architecture decision.
- A composition-registry/plugin/descriptor abstraction — the manual
  per-composition dispatch pattern is preserved, acknowledged as debt,
  and recorded for reconsideration at composition #4.
- Any change to Batch 25's AWS OIDC/bootstrap boundary — untouched.

## No `terraform apply`, still

Nothing about this composition changes this project's central safety
property: `TerraformRunner` has no `apply` method anywhere, no AWS
mutation of any kind ever occurs, and a GitHub pull request remains
the terminal artifact.

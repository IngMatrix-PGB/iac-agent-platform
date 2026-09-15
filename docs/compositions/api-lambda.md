# API Gateway → Lambda Composition (Phase 2, Batch 20)

## Why this composition, and why this document exists

Batch 19 introduced composition as a concept — a fixed, deterministic
multi-resource architecture (SQS → Lambda → DynamoDB) represented as
one top-level request. Batch 20 proves that architecture generalizes:
adding a **second** composition (API Gateway HTTP API → Lambda)
required no redesign of any core layer. It needed exactly what Batch
19's own design predicted — a new typed composition spec, a
deterministic renderer, composition-specific policies/Checkov
profile/eval dataset, and small dispatch-registration entries — never
an arbitrary graph/DAG system, a generic workflow engine, a generic IAM
generator, or a generic Terraform module composer.

## Architecture

```
API Gateway HTTP API  ---(proxy integration + one explicit route)--->  Lambda
```

A client request to the one explicit `METHOD /path` route this
composition's contract requires triggers the Lambda function via a
proxy integration; the function is granted permission to be invoked by
API Gateway — nothing else. The trusted fixture package this platform
already uses for every Lambda request (see `docs/resources/lambda.md`)
does not implement any HTTP application behavior — Batch 20 validates
infrastructure composition, not a sample business application.

## API Gateway modeling decision: Option A

Batch 20 evaluated two ways to model API Gateway:

- **Option A** — API Gateway exists as a reusable trusted resource/
  module/spec (`ApiGatewayResourceSpec`, `terraform/modules/
  api_gateway`), and the composition owns the route/integration/
  permission relationships.
- **Option B** — API Gateway exists only inside the `ApiLambdaSpec`
  composition, with no standalone resource contract at all.

**Option A was chosen.** It produces exactly the same clean boundary
already established by SQS/S3/DynamoDB/Lambda: `ResourceType.
API_GATEWAY` is a full resource-type citizen (its own contract,
renderer, trusted module, platform-policy entry, Checkov profile,
trusted-module-directory entry, and display name), and the composition
layer reuses it verbatim rather than inlining a duplicate. This mirrors
Batch 19's own precedent of reusing `SQSResourceSpec`/
`LambdaResourceSpec`/`DynamoDBResourceSpec` unchanged.

## Resource identity vs. architecture identity

`ResourceType.API_GATEWAY = "api_gateway"` classifies the standalone
AWS resource; `CompositionType.API_GATEWAY_LAMBDA = "api_gateway_lambda"`
(kept fully separate, in `iac_agent.domain.composition`) classifies the
architecture. There is still no `ResourceType.SERVERLESS` and no
`ResourceType.IAM` — neither this batch nor Batch 19 found a concrete
blocker requiring either.

## The resource contract: `ApiGatewayResourceSpec`

```python
ApiGatewayResourceSpec(
    name: str,
    description: str | None = None,
    environment: str | None = None,
    tags: dict[str, str] = {},
)
```

Protocol type is always **HTTP** — there is no field through which a
caller could request `WEBSOCKET`; the trusted module hardcodes
`protocol_type = "HTTP"` unconditionally. This is deliberately the
smallest useful API Gateway contract: no routes, no stages beyond the
one the module itself owns, no authorizers, no custom domains, no WAF.

## The trusted module: `terraform/modules/api_gateway`

Owns exactly two resources, verified against the real AWS provider
schema (`terraform providers schema -json`) before writing `main.tf`:

- `aws_apigatewayv2_api.this` — `protocol_type` hardcoded to `"HTTP"`;
  `name`/`description`/`tags` from the spec.
- `aws_apigatewayv2_stage.default` — a single managed stage named
  exactly `"$default"`, with `auto_deploy = true`. No dev/staging/prod
  stage management this batch.

### Module outputs

`api_id`, `api_endpoint`, and `execution_arn` — the smallest set the
composition layer concretely needs (`execution_arn` specifically for
scoping the Lambda invocation permission below). No other internal
attribute is exposed.

## The composition contract: `ApiLambdaSpec`

```python
ApiLambdaSpec(
    name: str,
    environment: str | None = None,
    api: ApiGatewayResourceSpec,
    function: LambdaResourceSpec,
    route: RouteSpec,
    tags: dict[str, str] = {},
)
```

`api` and `function` are exactly the existing `ApiGatewayResourceSpec`/
`LambdaResourceSpec` — never duplicated field definitions. Cross-
resource invariants mirror `ServerlessWorkerSpec`'s exactly:
pairwise-distinct `api.name`/`function.name` (no shared-name guessing —
this platform never silently renames a resource to force uniqueness),
and environment consistency between the composition and its sub-specs.

## The route model

```python
class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class RouteSpec(BaseModel):
    method: HttpMethod
    path: str
```

`ANY` is deliberately not a member — no demonstrated need for it this
batch. `RouteSpec.route_key` is a derived property
(`f"{method} {path}"`, e.g. `"POST /orders"`) — the exact `route_key`
value the renderer places onto `aws_apigatewayv2_route`. There is no
implicit `$default` catch-all route anywhere: a route is only ever
created because a caller supplied both a method and a path explicitly.

### Path validation

Deliberately not the full API Gateway route-path grammar — just enough
to reject the obviously wrong inputs, verified case by case:

- Must start with `/`; `/` alone is valid (the API root).
- No trailing slash except the bare root `/`.
- No empty segments (`/orders//list` is rejected).
- No whitespace, no control characters, bounded length (512 chars).
- Each segment is either a plain literal (`orders`) or a
  `{param}`-style placeholder (`{id}`) — no greedy `{proxy+}` support.

## Lambda proxy integration

Exactly one `aws_apigatewayv2_integration`, with fixed, non-caller-
configurable values:

- `integration_type = "AWS_PROXY"`
- `integration_method = "POST"` — this is the HTTP method API Gateway
  itself uses to call the Lambda `Invoke` API internally, **independent**
  of the route's own client-facing method (a `GET /orders` route still
  uses `integration_method = "POST"`).
- `payload_format_version = "2.0"` — the current recommended format
  (verified against current AWS API Gateway documentation: `1.0` and
  `2.0` are the only supported values, and every non-console caller
  must specify one explicitly).
- `integration_uri = module.function.function_arn` — a real module-
  output reference, never a synthesized ARN.

## The route

Exactly one `aws_apigatewayv2_route`, with `route_key` set to
`RouteSpec.route_key` and `target` pointing at the integration
(`"integrations/${aws_apigatewayv2_integration.lambda.id}"`).

## Critical IAM distinction: execution role vs. invocation permission

This is the central Batch 20 constraint, and it is enforced
structurally, not just documented:

- **The Lambda execution role** (`module.function`'s own
  `aws_iam_role`, owned entirely by the trusted Lambda module from
  Batch 18) describes what the **function itself** may do —
  unconditionally, only its own CloudWatch Logs permissions, completely
  unaffected by this composition.
- **`aws_lambda_permission`** is a **Lambda resource-based permission**
  — a wholly separate mechanism describing who may **invoke** the
  function. This composition never adds anything to the execution role;
  it only creates one `aws_lambda_permission` resource.

```hcl
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "<composition-name>-apigateway-invoke"
  action        = "lambda:InvokeFunction"
  function_name = module.function.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api.execution_arn}/$default/<METHOD><path>"
}
```

`principal`/`action` are fixed, reviewed constants — there is no field
on `ApiLambdaSpec` through which a caller could change either or
introduce a wildcard. `source_arn` is scoped as narrowly as practical:
exactly this API's execution ARN, the one `$default` stage this batch
ever creates, and the exact route's method + path — never `/*/*`.
Proven directly against a real Terraform plan and a static read of the
renderer's own source in
`tests/integration/test_api_lambda_renderer_terraform.py`, including an
explicit assertion that the plan's only `aws_iam_role_policy` address is
the trusted Lambda module's own pre-existing logs policy — the
composition adds none of its own.

## No generic IAM policy DSL

Nothing in this batch introduces `permissions: list[PermissionSpec]`,
`actions: list[str]`, or `resources: list[str]` anywhere in the public
contract. `_INVOKE_PRINCIPAL`/`_INVOKE_ACTION` are fixed, checked-in
constants in `iac_agent.compositions.api_lambda.renderer` — not a
caller-configurable field.

## Environment references

Batch 20 injects **no** environment variables into the function at
all — unlike the serverless-worker composition's `QUEUE_URL`/
`TABLE_NAME`, there is no analogous value this composition's contract
needs the function to receive (the API endpoint is not injected, since
nothing in this batch's scope reads it back). `LambdaResourceSpec`'s
own `environment_variables` field still works exactly as it does
standalone.

## Trusted module reuse

The renderer instantiates the two already-existing trusted modules
side by side — `module "api"` (`terraform/modules/api_gateway`) and
`module "function"` (`terraform/modules/lambda`) — and adds only the
relationship resources not naturally owned by either
(`aws_apigatewayv2_integration`, `aws_apigatewayv2_route`,
`aws_lambda_permission`). No resource implementation is ever
duplicated; no api_lambda-specific copy of either trusted module was
created.

## Composition policies

`iac_agent.policies.composition.evaluate_composition_policies` (the
same dispatcher Batch 19 introduced, now also matching `ApiLambdaSpec`)
runs:

| Policy ID | Outcome | Evidence source |
|---|---|---|
| `API_LAMBDA_INVOKE_PERMISSION_REQUIRED` | always PASS | the renderer's fixed choice to always emit exactly one invocation permission — no field could omit it |
| `API_LAMBDA_NO_WILDCARD_PRINCIPAL` | always PASS, evidence-only | the renderer's fixed `principal`/`action` constants, proven never a wildcard via a real plan |
| `API_LAMBDA_ROUTE_EXPLICIT` | always PASS | `ApiLambdaSpec.route` is a required field — no representable spec has a missing/implicit route |
| `LAMBDA_TRACING_RECOMMENDED` | PASS/WARN, reused verbatim from `iac_agent.policies.platform` | the function sub-spec's own tracing mode |
| `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED` | PASS/WARN, reused verbatim | the function sub-spec's own reserved-concurrency setting |
| `TF_NO_DESTRUCTIVE_CHANGES` | shared with every other resource/composition type | the rendered `PlanSummary` |

There is no DynamoDB/SQS-style sub-policy to reuse here (this
composition has no such sub-resource), and deliberately no separate IAM
platform policy — the invocation permission's safety is a trusted-
renderer invariant and a Checkov concern.

### Policy boundary: what plan-time evidence can and cannot support

`aws_lambda_permission.source_arn` references the not-yet-created
API's own `execution_arn` — genuinely **unknown** at credential-free
plan time, verified empirically (`after_unknown`) before writing the
corresponding assertion, exactly like every prior cross-module IAM
reference in this project. `evaluate_composition_policies` never
pretends otherwise: it does not parse or re-derive that value. The
concrete scoping expression is instead verified via a direct, justified
static read of the renderer's own checked-in source.

## Checkov: one carried-forward union, one genuinely new finding

A real, **strict** (zero-skip) Checkov scan was run first against the
composition's own rendered secure baseline — never an automatic union
of constituent skip lists assumed in advance:

- Real scan result: 9 managed resources, 41 passed, 7 failed.
- Six of the seven findings are exactly the already-approved API
  Gateway skip (`CKV_AWS_76`, access logging) and Lambda's five
  already-approved skips (`CKV_AWS_117`, `CKV_AWS_116`, `CKV_AWS_158`,
  `CKV_AWS_173`, `CKV_AWS_272`) — no new decision needed for those.
- The seventh, **`CKV_AWS_309`** ("Ensure API GatewayV2 routes specify
  an authorization type"), is a genuinely **new** finding that never
  appeared in any prior batch's profile. It was surfaced to the project
  owner via `AskUserQuestion` before being added — classified as a
  declared Batch 20 non-goal (this batch adds no authorization
  mechanism of any kind), not a defect or a tooling mismatch. The
  project owner explicitly approved adding it as a targeted skip.

`iac_agent.security.composition_checkov_profiles.
composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA)`
returns exactly these seven skips — never S3's four skips, never
DynamoDB's `CKV_AWS_119`, proven by a dedicated unit test.

## HITL

No semantic change: a clean PASS/WARN composition still pauses at
`AWAITING_APPROVAL`; a BLOCK result still terminates at `BLOCKED` with
no interrupt ever reached.

## Source control

`source_control`'s PR/commit text branches on the request kind:

```
feat(iac): add API Lambda proposal <request_id>
```

and the PR body states the composition type, API, route, and Lambda
name instead of a single "Resource type:"/"Resource:" pair — never a
raw Terraform dump either way:

```
Request ID: <request_id>
Composition type: api_gateway_lambda
API: <api name>
Route: <METHOD> <path>
Lambda: <function name>
Security status: <pass|warn>
Plan: 9 to add, 0 to change, 0 to destroy
Human approval: approved
```

## Request-level dispatch

`iac_agent.request.IacRequestSpec` widens again, to `AWSResourceSpec |
ServerlessWorkerSpec | ApiLambdaSpec`; `IacRenderer` gains one more
explicit `match`/`case` branch (`ApiLambdaSpec ->
ApiLambdaTerraformRenderer`), computing the module-source pair it needs
from the same `ResourceType`-keyed `trusted_module_dirs` mapping every
resource type already used — no new `CompositionType`-keyed trusted-
module map, exactly like Batch 19.

## Workflow integration

`iac_agent.graph.workflow.build_iac_workflow` is still the one shared
entry point — no `build_api_lambda_workflow`, no new graph node. Every
`match`/`case` branch Batch 19 added for `ServerlessWorkerSpec` simply
widened to `ServerlessWorkerSpec() | ApiLambdaSpec()` (the underlying
`evaluate_composition_policies`/`composition_checkov_profile_for`/
`REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE` dispatch on the
spec's own type internally, so no second gate function was needed).

## Application layer

`iac_agent.app.service.IacApplication` (the Batch 19 rename;
`Phase1Application` kept as an alias) needed no changes at all for
`ApiLambdaSpec` — the same reasoning as Batch 19's serverless-worker
composition: `open_application`'s compiled graph already builds via the
fully request-generalized `build_iac_workflow`.

### `ApplicationConfig.terraform_module_path`: removed, not merely deferred

Batch 20 re-evaluated this tracked naming debt and found it was
**demonstrably dead configuration**, not merely undocumented: it was
never read from any environment variable
(`load_application_config_from_env` always computed it from a fixed
internal constant), and that constant was always identical to what
`build_sqs_workflow`'s own `trusted_module_dir` default parameter
already resolves to. Passing it through in `open_application` changed
nothing at runtime. It has been removed from `ApplicationConfig`
entirely, with regression tests proving both the field's absence and
that `open_application`'s SQS behavior is unchanged (see
`tests/unit/app/test_config.py` and
`tests/integration/test_application_composition.py`). Trusted-module-
directory resolution lives entirely in `iac_agent.graph.workflow.
_DEFAULT_TRUSTED_MODULE_DIRS` now, resource- and composition-aware for
every type this platform supports.

## Persistence

`ApiGatewayResourceSpec`, `ApiLambdaSpec`, `HttpMethod`, and `RouteSpec`
all round-trip through the SQLite checkpointer with no pickle
fallback — proven via a close/reopen/reconstruct cycle (new saver, new
compiled graph, same database file) in
`tests/integration/test_api_lambda_workflow_persistence.py`.

## Explicit non-goals (this batch)

- Authorization of any kind: Cognito, JWT authorizers, Lambda
  authorizers, IAM route auth, API keys. (`CKV_AWS_309` documents this
  exact gap — future hardening.)
- WAF — future production-edge hardening.
- Custom domains: ACM, Route53, base-path mappings.
- A configurable CORS surface — if API Gateway requires none, this
  batch leaves it absent rather than adding a broad CORS DSL.
- A second Lambda (producer/consumer split) — exactly one function.
- Any expansion of SQS's DLQ behavior or a Lambda-side DLQ/destination
  configuration — unrelated to this composition entirely.
- S3 — not part of this composition.
- Chaining this composition with the serverless-worker composition
  (API Gateway → Lambda → SQS → Lambda → DynamoDB) — a later,
  explicitly separate composition, not this batch's.
- A generic IAM top-level resource type or a generic IAM policy DSL.
- `terraform apply`/`destroy` — still never present anywhere in this
  codebase.

## No `terraform apply`, still

Nothing about api_lambda support changes this project's central safety
property: `TerraformRunner` has no `apply` method anywhere, no AWS
mutation of any kind ever occurs, and a GitHub pull request remains the
terminal artifact for this composition exactly as it is for every other
resource/composition type.

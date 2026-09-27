# Batch 26 — API Gateway → Lambda → DynamoDB composition (design)

Discovery base: `origin/main` `8f8ce8a` (PR #8, Batch 25's AWS plan
boundary/OIDC foundation, merged 2026-09-27T02:59:53Z). This document
is design-only: no `terraform apply`, no `terraform destroy`, no AWS
mutation, no real AWS credentials, no repository code change. Batch 25
Tasks 12–16 (real AWS bootstrap/OIDC) are untouched and remain
deferred — nothing here reads, writes, or reasons about
`bootstrap/aws-oidc/` or `ci/aws_plan/`.

## 0. Corrected premise (recorded, not re-litigated)

The Batch 26 kickoff message's framing ("evolve from a single
`sqs_lambda_dynamodb` vertical slice") did not match repository
evidence. `main` already has two compositions
(`CompositionType.SQS_LAMBDA_DYNAMODB`, added Batch 19;
`CompositionType.API_GATEWAY_LAMBDA`, added Batch 20 — see
`docs/roadmap.md:258-259`, which states Batch 20's own goal was
exactly to prove the architecture generalizes past one composition).
The human reviewing the Batch 26 discovery report confirmed this
correction explicitly ("BATCH 26 — COMPOSITION DECISION", item 1).
This design is therefore for **composition #3**:
`CompositionType.API_GATEWAY_LAMBDA_DYNAMODB`.

## 1. Target intent mapping

Resolved by `ArchitectureIntent`:

```
workload_type       = WorkloadType.API
interaction_pattern = InteractionPattern.SYNCHRONOUS
capabilities        = frozenset({Capability.HTTP_ENDPOINT, Capability.PERSISTENCE})
```

No new `WorkloadType`, `InteractionPattern`, or `Capability` member is
added — this exact combination is representable today and currently
falls through `ArchitectureResolver.resolve()`'s `case _` arm
(`src/iac_agent/intent/resolver.py:233-242`) to
`UnsupportedArchitecture` (`UNSUPPORTED_COMBINATION`, since
`workload_type != WorkloadType.STORAGE`). The LLM-visible vocabulary
does not change at all — this is the strongest possible confirmation
that "LLM interprets, deterministic code selects" holds without any
weakening.

## 2. Resolver precedence and exact intent matching

`ArchitectureResolver.resolve()`'s `match` is evaluated top-to-bottom,
but correctness here does not depend on ordering: every existing arm
guards on `capabilities == frozenset({...})` (exact-set equality, never
subset/superset), so `frozenset({HTTP_ENDPOINT})` and
`frozenset({HTTP_ENDPOINT, PERSISTENCE})` are different values and can
never both match the same intent. Two new arms are added, placed
directly after the existing `API_GATEWAY_LAMBDA` arm and its
clarification counterpart (readability only, not a correctness
requirement):

```python
case WorkloadType.API if (
    interaction_pattern == InteractionPattern.SYNCHRONOUS
    and capabilities == frozenset({Capability.HTTP_ENDPOINT, Capability.PERSISTENCE})
):
    return ResolvedArchitecture(
        request_spec=_build_api_lambda_dynamodb_spec(intent, request_id=request_id),
        matched_pattern="api+synchronous+http_endpoint+persistence",
    )
...
case WorkloadType.API if (
    interaction_pattern == InteractionPattern.UNSPECIFIED
    and capabilities == frozenset({Capability.HTTP_ENDPOINT, Capability.PERSISTENCE})
):
    return ClarificationRequired(request=_interaction_pattern_clarification())
```

The second arm is not optional — without it, an intent with the right
capability set but an unresolved `interaction_pattern` would fall
through to `UnsupportedArchitecture` instead of asking for
clarification, silently changing behavior for a case that should be
recoverable (mirrors the existing bare-`HTTP_ENDPOINT` and
worker-capability clarification arms exactly).

`WorkloadType.API` + `ASYNCHRONOUS` + this same capability set remains
unmapped and correctly falls to `UnsupportedArchitecture` — no change,
already fail-closed, not addressed by this batch (see the discovery
report's rejected "async API" candidate).

## 3. `ApiLambdaDynamoDbSpec` contract

New file: `src/iac_agent/compositions/api_lambda_dynamodb/contract.py`.

**Human decision, item 3, already locked:** this is a distinct Pydantic
model, not an extension of `ApiLambdaSpec` and not a subclass of it.
This is not just a naming preference — Python's structural pattern
matching (`case ApiLambdaSpec():`) and `isinstance()` both test the
concrete/base class, so a genuinely separate, non-subclassing model is
what mechanically guarantees `ApiLambdaDynamoDbSpec` can never be
matched by any existing `case ApiLambdaSpec():`/`isinstance(spec,
ApiLambdaSpec)` site — this is verifiable directly (§9's regression
tests), not just asserted.

```python
class ApiLambdaDynamoDbSpec(BaseModel):
    """Canonical, validated representation of a requested API-Gateway-
    HTTP-API -> Lambda -> DynamoDB composition (a synchronous REST API
    backed by one DynamoDB table). Deliberately not a superset of
    ApiLambdaSpec's fields reused via inheritance — see module docstring
    for why this must be a structurally distinct type.
    """

    composition_type: Literal["api_gateway_lambda_dynamodb"] = "api_gateway_lambda_dynamodb"
    name: str
    environment: str | None = None
    api: ApiGatewayResourceSpec
    function: LambdaResourceSpec
    route: RouteSpec          # reused verbatim from iac_agent.compositions.api_lambda.contract
    table: DynamoDBResourceSpec
    tags: dict[str, str] = Field(default_factory=dict)

    # validators, mirroring ApiLambdaSpec/ServerlessWorkerSpec exactly:
    #  - name pattern/length (shared _validate_composition_name, same regex/bounds)
    #  - api.name, function.name, table.name pairwise distinct (extends
    #    ApiLambdaSpec's pairwise check from 2 to 3 names, same style as
    #    ServerlessWorkerSpec's 3-way check)
    #  - environment consistency across api/function/table (same pattern
    #    as both existing compositions, extended to a third sub-spec)
```

`RouteSpec`/`HttpMethod` are **imported and reused** from
`iac_agent.compositions.api_lambda.contract`, not duplicated — exactly
how `ServerlessWorkerSpec`/`ApiLambdaSpec` already reuse
`SQSResourceSpec`/`DynamoDBResourceSpec`/`LambdaResourceSpec`/
`ApiGatewayResourceSpec` verbatim from `providers.aws.*`. This creates
one new cross-composition import
(`compositions.api_lambda_dynamodb` → `compositions.api_lambda`) that
does not exist today (currently every composition only imports from
`providers.aws.*`, never from a sibling composition) — flagged in §12
as a minor precedent change, not a problem: `RouteSpec` is a pure,
dependency-free domain type, so this does not create a cycle or couple
the two compositions' renderers/policies to each other.

**Open design question (needs sign-off, see §13 close):** should this
route stay singular, matching `ApiLambdaSpec`'s one-`RouteSpec` design
exactly (recommended, see §4/§5), or should the contract support
multiple routes for a more realistic CRUD API? This is the single
biggest scope lever in this design.

## 4. Naming derivation and validation

No change to `iac_agent.intent.naming` — it already operates purely on
`base: str, suffix: str`. The resolver-owned builder follows the
serverless-worker/api-lambda pattern exactly:

```python
def _build_api_lambda_dynamodb_spec(
    intent: ArchitectureIntent, *, request_id: str
) -> ApiLambdaDynamoDbSpec:
    base = resolve_base_name(logical_name_hint=intent.logical_name_hint, request_id=request_id)
    return ApiLambdaDynamoDbSpec(
        name=base,
        api=ApiGatewayResourceSpec(name=component_name(base, "api")),
        function=LambdaResourceSpec(
            name=component_name(base, "function"), handler=LAMBDA_DEFAULT_HANDLER
        ),
        route=API_LAMBDA_DEFAULT_ROUTE,  # reused verbatim, see §5
        table=DynamoDBResourceSpec(
            name=component_name(base, "table"),
            partition_key=WORKER_DDB_DEFAULT_PARTITION_KEY,  # reused verbatim, see §5
        ),
    )
```

Every existing resolver-owned fixed default
(`LAMBDA_DEFAULT_HANDLER`, `API_LAMBDA_DEFAULT_ROUTE`,
`WORKER_DDB_DEFAULT_PARTITION_KEY`) is reused **verbatim, unmodified**
— none of these three module-level constants change meaning or value
for the existing two compositions; this is purely additive.

## 5. Defaults (CLOSED — "BATCH 26 — DESIGN DECISIONS APPROVED")

- **Exactly one route**, reusing `API_LAMBDA_DEFAULT_ROUTE`
  (`POST /invoke`) unchanged — not a new, second fixed default.
  **Decided:** one fixed route, following `ApiLambdaSpec` exactly.
  Multi-route support is explicitly out of scope for Batch 26 — this
  batch validates composition #3, it does not introduce a generalized
  API-routing abstraction. Any future multi-route need is a separate,
  later architecture decision.
- **Exactly one DynamoDB partition key**, reusing
  `WORKER_DDB_DEFAULT_PARTITION_KEY` (`id`, string) unchanged.
- **Exactly one Lambda→DynamoDB IAM action: `dynamodb:PutItem`,
  scoped to the generated table's ARN.** **Decided:** grant exactly
  `dynamodb:PutItem` — never `GetItem`, `UpdateItem`, `DeleteItem`,
  `Query`, `Scan`, `BatchWriteItem`, a wildcard action, or any broader
  CRUD set. This matches `ServerlessWorkerSpec`'s existing minimal
  grant exactly (§6). Any additional DynamoDB behavior (read access,
  updates, deletes) requires a future, explicit
  architecture/capability decision — it is never added preventively or
  speculatively ahead of a demonstrated need.

## 6. Renderer and Terraform module wiring

New file: `src/iac_agent/compositions/api_lambda_dynamodb/renderer.py`.

Reuses all three existing trusted modules
(`terraform/modules/api_gateway`, `terraform/modules/lambda`,
`terraform/modules/dynamodb`) — **no new Terraform module is
introduced**, confirming discovery's finding that this composition
needs no new primitive. The renderer is built by combining, verbatim,
the two rendering techniques that already exist independently:

- `_render_api_module_block` / `_render_function_module_block` /
  `_render_integration_block` / `_render_route_block` /
  `_render_lambda_permission_block` — copied from
  `iac_agent.compositions.api_lambda.renderer` (same fixed
  `AWS_PROXY`/`"2.0"`/`apigateway.amazonaws.com` constants, same
  execute-api ARN scoping grammar).
- `_render_table_module_block` and a new
  `_render_dynamodb_write_policy_block` — modeled directly on
  `iac_agent.compositions.serverless_worker.renderer`'s own
  `_render_table_module_block`/`_render_dynamodb_write_policy_block`,
  reusing the exact same "Option B" IAM pattern: a composition-owned
  `aws_iam_role_policy` resource, `role =
  module.function.execution_role_name` (the trusted Lambda module's
  existing output — no change to `terraform/modules/lambda` at all),
  scoped to exactly the new table's ARN, action(s) per §5.

`ApiLambdaDynamoDbModuleSources` (new `@dataclass(frozen=True)`, mirrors
`ApiLambdaModuleSources`/`ServerlessWorkerModuleSources` exactly):
`api: str`, `function: str`, `table: str`.

No raw `aws_apigatewayv2_api`, `aws_lambda_function`, `aws_iam_role`,
or `aws_dynamodb_table` block is ever emitted by this renderer — those
remain exclusively owned by the three trusted modules, exactly like
both existing composition renderers.

**Code duplication note (acknowledged, not fixed this batch):** the
API-Gateway-integration/route/permission rendering functions would be
near-verbatim copies between `api_lambda/renderer.py` and the new
`api_lambda_dynamodb/renderer.py`. Per the human decision (item 4), no
shared-descriptor/registry abstraction is introduced this batch — this
duplication is accepted now and explicitly recorded as debt for
reconsideration at composition #4 (§12), the same way the human
decision already treats the dispatch-site duplication.

## 7. Composition policy IDs and dispatch

`src/iac_agent/policies/composition.py`:

- New policy-ID constants (mirroring the existing naming convention,
  `SERVERLESS_*` / `API_LAMBDA_*`):
  - `API_LAMBDA_DYNAMODB_INVOKE_PERMISSION_REQUIRED`
  - `API_LAMBDA_DYNAMODB_NO_WILDCARD_PRINCIPAL`
  - `API_LAMBDA_DYNAMODB_ROUTE_EXPLICIT`
  - `API_LAMBDA_DYNAMODB_WRITE_SCOPE_REQUIRED`
  - `API_LAMBDA_DYNAMODB_NO_WILDCARD_IAM`
- New `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[CompositionType.API_GATEWAY_LAMBDA_DYNAMODB]`
  entry: the five IDs above, plus the reused
  `LAMBDA_TRACING_RECOMMENDED`, `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED`,
  `DDB_PITR_RECOMMENDED`, `DDB_DELETION_PROTECTION_RECOMMENDED`,
  `TF_NO_DESTRUCTIVE_CHANGES` — the same reused-verbatim sub-policies
  `ServerlessWorkerSpec` already runs against its own `table`, applied
  here against `spec.table` unchanged (`evaluate_dynamodb_pitr_policy`,
  `evaluate_dynamodb_deletion_protection_policy` take a
  `DynamoDBResourceSpec`, not a composition type — no change needed to
  either function).
- New `case ApiLambdaDynamoDbSpec():` arm in
  `evaluate_composition_policies()`, combining: the three
  `_evaluate_api_lambda_*` findings (invoke permission, no-wildcard
  principal, route-explicit — reused conceptually, re-authored against
  the new spec type since Python's structural typing can't share a
  function across two different Pydantic models without a common
  protocol, which item 4 rules out introducing this batch), one new
  `_evaluate_api_lambda_dynamodb_write_scope_policy` (mirrors
  `_evaluate_dynamodb_write_scope_policy` exactly), one new
  `_evaluate_no_wildcard_iam_policy` variant (or the existing
  parameterless one reused as-is, since it takes no spec argument at
  all today — reusable verbatim), plus
  `evaluate_lambda_tracing_policy(spec.function)`,
  `evaluate_lambda_reserved_concurrency_policy(spec.function)`,
  `evaluate_dynamodb_pitr_policy(spec.table)`,
  `evaluate_dynamodb_deletion_protection_policy(spec.table)`.

## 8. Checkov profile — discovery methodology (CLOSED — never a union)

`src/iac_agent/security/composition_checkov_profiles.py` gets one new
`CompositionType.API_GATEWAY_LAMBDA_DYNAMODB` entry, produced by the
following approved, ordered, empirical procedure (implementation-time
work — needs the real renderer to exist first; this design fixes only
the *methodology*, never the resulting skip list):

1. Implement the renderer (§6).
2. Render the real composition (a real, secure-default
   `ApiLambdaDynamoDbSpec` — credential-free, no AWS call).
3. Run the existing strict real-tool Checkov path against it with
   **zero** composition-specific skips initially.
4. Capture the actual reported findings.
5. Evaluate each finding individually against this specific
   three-resource combination — never assumed from either existing
   profile.
6. Add only empirically justified skips (each with the same kind of
   written evidence/citation this project's existing profiles already
   carry).
7. Freeze the resulting profile in code and in a regression test.
8. Prove the final strict scan (with only the frozen skips applied)
   passes cleanly.

**Never** obtained by unioning `api_lambda`'s and `serverless_worker`'s
existing approved skip lists — a superficially similar shortcut this
project used successfully for `serverless_worker` (whose profile *was*
verified to equal a union, but only after running the real scan first
and checking, not by assumption) is explicitly rejected here as a
starting method, not just as a final answer.

## 9. All dispatch sites requiring recognition of the new type

Exhaustive, confirmed by `grep -rn "ApiLambdaSpec\b" src/` against
`main` `8f8ce8a` (every existing site the second composition had to
touch, found the same way):

| # | File | Change |
|---|---|---|
| 1 | `domain/composition.py` | new `CompositionType.API_GATEWAY_LAMBDA_DYNAMODB` member |
| 2 | `compositions/api_lambda_dynamodb/contract.py` | new file (§3) |
| 3 | `compositions/api_lambda_dynamodb/renderer.py` | new file (§6) |
| 4 | `compositions/resource.py` | `CompositionSpec` union widened; new `case ApiLambdaDynamoDbSpec():` arm in `composition_type_of()` |
| 5 | `request.py` | `IacRequestSpec` union widened; `IacRenderer.__init__` new optional `api_lambda_dynamodb_renderer` param; new `case ApiLambdaDynamoDbSpec():` arm in `.render()` |
| 6 | `intent/resolver.py` | two new `match` arms (§2) + `_build_api_lambda_dynamodb_spec()` (§4) |
| 7 | `policies/composition.py` | new arm + IDs (§7) |
| 8 | `security/composition_checkov_profiles.py` | new profile entry (§8) |
| 9 | `graph/workflow.py` | **five** sites: `_pr_body()` new `case` (identity_lines: API/route/Lambda/table); commit-message block new `case` (`resource_kind = "API Lambda DynamoDB"`, exact string TBD at implementation); the three grouped `case ServerlessWorkerSpec() \| ApiLambdaSpec():` arms (platform_policy, checkov_scan, security_gate) widened to `\| ApiLambdaDynamoDbSpec()`; `build_iac_workflow()` new optional `api_lambda_dynamodb_renderer` parameter, threaded into `IacRenderer(...)` |
| 10 | `cli/present.py` | `_architecture_label()` new `isinstance` branch (fixing the same-named function's unconditional `"s3"` fallback for anything not already recognized — a real, pre-existing sharp edge this composition would otherwise silently mis-label); `_component_lines()` new branch listing `api`/`route`/`function`/`table` (all three underlying resources, per human decision item 5) |
| 11 | `persistence/checkpoints.py` | `_ALLOWED_WORKFLOW_TYPES` new entry: `("iac_agent.compositions.api_lambda_dynamodb.contract", "ApiLambdaDynamoDbSpec")` — **easy to miss, directly threatens "durable HITL behavior remains unchanged"** if omitted: an omitted entry means `JsonPlusSerializer` cannot serialize a checkpointed `WorkflowState` containing this spec, breaking resume for this composition specifically while leaving the other two untouched (a silent, composition-specific durability regression, not a crash at submit time) |

**Confirmed needing no change** (verified this session, not assumed):
`app/composition.py` (`build_iac_workflow`'s own defaults already cover
every resource/composition type — verified against its own docstring
plus `_DEFAULT_TRUSTED_MODULE_DIRS`); `build_sqs_workflow()` (never
composition-aware, per its own docstring); `intent/naming.py`;
`security/gate.py` (`evaluate_security_gate`'s `required_policy_ids`
parameter is already composition-agnostic); `domain/plan.py`,
`domain/security.py` (no composition awareness in either); the three
existing trusted Terraform modules themselves (no change to
`api_gateway`, `lambda`, or `dynamodb` modules — the Lambda module's
`execution_role_name` output already exists and is reused unchanged).

## 10. HITL / PR / CLI presentation (cosmetic decisions CLOSED)

- **Commit message / `resource_kind` (CLOSED):**
  `resource_kind = "api lambda dynamodb"`, exactly as approved —
  matching the existing lowercase-with-spaces style
  (`"serverless worker"`) rather than `ApiLambdaSpec`'s own
  `"API Lambda"` casing; this is the approved literal string, not a
  free choice.
- **Human-readable architecture label (CLOSED):** an equivalent of
  `"API Gateway + Lambda + DynamoDB"` — used consistently everywhere
  the composition's architecture is described to a human (PR body's
  `Composition type:` line context, CLI output), not a different
  wording in each place. Per human decision item 3, this consistency is
  achieved by defining the exact string **once**, as a plain module-level
  constant, and importing it into `graph/workflow.py` and
  `cli/present.py` — **not** by introducing a descriptor/registry
  abstraction (explicitly ruled out for this batch, same as §13's
  standing decision).
- **PR body** (`_pr_body()` in `graph/workflow.py`): new `identity_lines`
  block, mirroring the `ApiLambdaSpec` shape plus the table line:
  `Composition type: api_gateway_lambda_dynamodb`, `API: <name>`,
  `Route: <method> <path>`, `Lambda: <name>`, `Table: <name>`.
- **CLI** (`cli/present.py`): `_architecture_label()` returns the new
  label; `_component_lines()` lists all three resources (api, route,
  function, table) — satisfying human decision item 5's explicit CLI
  requirement. A dedicated regression test proves this composition
  never falls through to the pre-existing unconditional `"s3"`
  fallback (§9 row 10, §14).
- **HITL / durable resume**: no change to the approval-gate mechanics
  themselves (`graph/workflow.py`'s interrupt/resume logic is already
  fully request-shape-agnostic — it only reads `plan_summary`,
  `security_gate`, and `approval_decision`, never branches on spec
  type). The only durability-relevant change is the checkpoint
  allowlist entry (§9, row 11) — treated as a **critical dispatch
  boundary** per the closed decision below, with dedicated proof, not
  just an allowlist entry taken on faith.

**Critical regression invariant (closed, mandatory):**
`persistence/checkpoints.py`'s `_ALLOWED_WORKFLOW_TYPES` is a security-
and-correctness-relevant dispatch boundary, not incidental plumbing.
Implementation must prove, not just assert:
- `ApiLambdaDynamoDbSpec` survives real checkpoint
  serialization/deserialization through the actual
  `open_sqlite_checkpointer`/`JsonPlusSerializer` path (no fakes).
- A workflow paused at the HITL interrupt can be reconstructed in a
  **fresh** application/process (a new `open_sqlite_checkpointer` call
  against the same on-disk database, simulating a real process
  restart) and resumed with the exact original composition spec.
- The reconstructed spec's type is asserted to be exactly
  `ApiLambdaDynamoDbSpec` — and explicitly asserted to **not** degrade
  into `ApiLambdaSpec`, a primitive `AWSResourceSpec`, a raw `dict`, or
  any other type. A silent type-widening failure here (e.g. the
  allowlist entry missing and the serializer falling back to a
  permissive/dict representation) is exactly the failure mode this
  test exists to catch.

## 11. Golden-eval structure

Mirrors the established, deliberately-non-generalized per-composition
pattern exactly (see `evals/scenarios/serverless_worker_loader.py`'s
own docstring: "a deliberately separate module rather than a
generalized/parameterized loader" — an intentional convention, not
oversight, preserved here):

- `evals/datasets/api_lambda_dynamodb_golden.json` — new dataset,
  schema shaped like `api_lambda_golden.json` plus `table_name`/
  DynamoDB-relevant expected fields (point_in_time_recovery,
  deletion_protection), mirroring how `serverless_worker_golden.json`
  extended `sqs_golden.json`'s shape.
- `evals/scenarios/api_lambda_dynamodb_loader.py` (new,
  `ApiLambdaDynamoDbScenario`/`ApiLambdaDynamoDbExpectedOutcome`
  dataclasses, same required-keys-when-valid discipline).
- `evals/scenarios/api_lambda_dynamodb_runner.py` (new).
- `evals/evaluators/api_lambda_dynamodb.py` (new).

## 12. Backward-compatibility guarantee for compositions #1 and #2

No existing file's *behavior* changes for an existing
`ServerlessWorkerSpec`/`ApiLambdaSpec` request — every touched file in
§9 only gains a new `case`/`isinstance` arm or a new dict entry; no
existing arm, constant, or default is edited. This is verified, not
assumed, by the regression tests in §14 (backward-compat suite) which
re-run the full existing Batch 19/20 test suites unmodified and add new
tests asserting the new composition is invisible to old dispatch
arms.

## 13. Design debt explicitly recorded (per human decision item 4)

The following remain **explicit, human-acknowledged debt**, not fixed
this batch: (a) manual per-composition `match`/`isinstance` branching
across 6+ files (§9); (b) near-duplicate API-Gateway-integration
rendering code between `api_lambda` and `api_lambda_dynamodb`
renderers (§6); (c) per-composition eval loader/runner/evaluator
duplication (§11, by design). Reconsideration trigger: composition #4,
or earlier if implementation reveals concrete duplication-caused error
(per the human decision's own stated threshold) — not before.

## 14. Test strategy (offline, no AWS/OIDC/OpenAI)

New, mirroring the existing per-composition file set exactly (8 files,
matching `serverless_worker`'s and `api_lambda`'s own counts):

- `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_contract.py`
- `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_renderer.py`
- `tests/unit/graph/test_workflow_api_lambda_dynamodb.py`
- `tests/integration/test_api_lambda_dynamodb_renderer_terraform.py` (real Terraform, credential-free — same technique as every other composition's real-tool test)
- `tests/integration/test_api_lambda_dynamodb_workflow_integration.py`
- `tests/integration/test_api_lambda_dynamodb_workflow_persistence.py` (the one that would catch a missing `_ALLOWED_WORKFLOW_TYPES` entry)
- `tests/integration/test_api_lambda_dynamodb_golden_evals.py`
- `tests/integration/test_api_lambda_dynamodb_golden_real_tool_eval.py`

**New regression tests specifically for the dangerous dispatch
boundaries** (human decision item 5, verbatim requirements), added to
the files above rather than as a separate suite:

1. `not isinstance(ApiLambdaDynamoDbSpec_instance, ApiLambdaSpec)` and
   `composition_type_of(...)` returns
   `CompositionType.API_GATEWAY_LAMBDA_DYNAMODB`, never
   `API_GATEWAY_LAMBDA` — proves the "never handled as `ApiLambdaSpec`"
   requirement mechanically, not just by construction.
2. `graph/workflow.py`'s platform_policy/checkov_scan/security_gate
   nodes, exercised end-to-end with an `ApiLambdaDynamoDbSpec` request,
   assert the *composition* path was taken (`evaluate_composition_policies`/
   `composition_checkov_profile_for`), never the single-resource
   fallback path — this is exactly the "grouped OR-arm forgotten"
   regression identified in the discovery report (§9 above).
3. PR-body and commit-message tests assert all three resource names
   (api/route/function/table) appear, for this composition only.
4. **CLI presentation regression (mandatory, closed):** a dedicated
   test asserts `_architecture_label()` returns the new label for
   `ApiLambdaDynamoDbSpec` and explicitly asserts it does **not** fall
   through to the pre-existing unconditional `"s3"` fallback — directly
   exercising the sharp edge found in §9 row 10; `_component_lines()`
   is asserted to list all three resources (api, route, function,
   table).
5. Resolver test: the two new capability combinations resolve/clarify
   correctly; every combination that should remain
   `UnsupportedArchitecture` (e.g. same capability set + `ASYNCHRONOUS`)
   still does.
6. Full existing `tests/unit`/`tests/integration` suites for
   `ServerlessWorkerSpec`/`ApiLambdaSpec` re-run unmodified and green —
   the explicit backward-compatibility proof (§12).
7. **Durable HITL reconstruction/resume proof (mandatory, closed) —**
   `test_api_lambda_dynamodb_workflow_persistence.py`: submit an
   `ApiLambdaDynamoDbSpec` request through the real graph to the HITL
   interrupt (real `open_sqlite_checkpointer`, on-disk SQLite, no
   fakes); close that checkpointer/process; open a **fresh**
   `open_sqlite_checkpointer` against the same database path (a real
   process-restart simulation, not just re-reading in the same
   session); reconstruct the paused state; assert the reconstructed
   `resource_spec` is exactly `ApiLambdaDynamoDbSpec` (`type(...) is
   ApiLambdaDynamoDbSpec`, not merely `isinstance` — to also rule out
   an accidental subclass); assert it is explicitly **not**
   `ApiLambdaSpec`, not a primitive `AWSResourceSpec`, not a raw
   `dict`; resume with an `APPROVE` decision through to
   `source_control`, proving the full HITL round trip. This is the
   concrete proof for §9 row 11's easy-to-miss allowlist entry —
   without it, this test fails loudly instead of the regression passing
   silently.

## 15. Contradictions discovered during design (none found)

No repository evidence contradicts the locked decisions from
"BATCH 26 — COMPOSITION DECISION." The one genuinely new fact surfaced
during design — `cli/present.py`'s `_architecture_label()` already has
an unconditional `"s3"` fallback for any unrecognized spec type — is
not a contradiction of a decision, it's a pre-existing minor sharp edge
this composition must not walk into; it's addressed in §9/§14, not
flagged as blocking.

## 16. Design decisions — CLOSED ("BATCH 26 — DESIGN DECISIONS APPROVED")

All four decisions previously open are now closed:

1. **Route cardinality:** exactly one fixed route, matching
   `ApiLambdaSpec` exactly (§5). Multi-route support is explicitly out
   of scope for Batch 26.
2. **IAM action set:** exactly `dynamodb:PutItem`, scoped to the
   generated table's ARN — never a broader or wildcard grant (§5).
3. **Presentation:** `resource_kind = "api lambda dynamodb"`; a single,
   centrally-defined human-readable label equivalent to `"API Gateway +
   Lambda + DynamoDB"`, reused everywhere (not a descriptor/registry
   abstraction) (§10).
4. **Checkov methodology:** approved exactly as the 8-step empirical
   procedure in §8 — never a union of the existing two profiles.

Plus one additional mandatory regression invariant, discovered during
design review and now locked: the durable HITL reconstruction/resume
proof and the `cli/present.py` `_architecture_label()` non-degradation
proof (§10, §14, items 4 and 7).

## 17. Design closure review against current repository evidence

Re-checked against `origin/main` `8f8ce8a` (no change since §0/§9's
original discovery — confirmed via `git rev-parse --short origin/main`
before writing this closure section): no new contradiction found.
Every dispatch site enumerated in §9 was verified by direct file
inspection this session (not assumed from memory), and none of them
have changed shape since. The four now-closed decisions do not
conflict with any locked architectural invariant (§0, §12, §13) or
with Batch 25's deferred-AWS boundary (untouched throughout: no file
under `bootstrap/aws-oidc/` or `ci/aws_plan/` was read, referenced, or
modified in this design work).

**No unresolved architectural contradiction remains.** Proceeding to
the implementation plan.

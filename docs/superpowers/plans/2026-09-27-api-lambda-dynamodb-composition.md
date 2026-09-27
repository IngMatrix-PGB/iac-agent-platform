# Batch 26 implementation plan — API Gateway → Lambda → DynamoDB composition

Design: `docs/superpowers/specs/2026-09-27-api-lambda-dynamodb-composition-design.md`
(all four open decisions closed, design closure review passed against
`origin/main` `8f8ce8a`). Not executed by writing this plan — requires
a separate, explicit "authorize implementation" message, mirroring
Batch 25's own plan→implementation gate.

**Gate structure:** two gates, matching the composition-batch pattern
(Batch 19/20), not the Batch-25 AWS/OIDC pattern — nothing in this
batch ever touches real AWS credentials, GitHub, or OpenAI, so there
is no Gate-C/D/E-style human-authorized-real-cloud step at all.

- **Gate A (Tasks 1–14):** fully deterministic and offline. No real
  Terraform, no real Checkov, no AWS, no GitHub, no OpenAI. Auto-runnable
  once implementation is authorized.
- **Gate B (Tasks 15–18):** real Terraform + real Checkov binaries,
  still fully credential-free (same technique every existing
  `real_tool`-marked test in this repository already uses — skip-flags
  or fake env vars, never a real AWS call).
- **Task 19:** closure checkpoint (full regression + report), no new
  production code.

Every task is one commit, test-first (RED before GREEN), following
this repository's own established discipline exactly as Batch 25's
plan did.

---

## Gate A — deterministic (offline, no real tools)

### Task 1: `CompositionType.API_GATEWAY_LAMBDA_DYNAMODB`

**Files:** `src/iac_agent/domain/composition.py`
**Objective:** add the third `CompositionType` member.
**Tests:** `tests/unit/domain/test_composition.py` (extend existing) — assert exactly three members exist, value is `"api_gateway_lambda_dynamodb"`.
**RED:** new test references the not-yet-existing member.
**Minimum implementation:** one new enum line + docstring update noting Batch 26 introduces the third member (mirrors the existing docstring's own "Batch 19 introduced the first member; Batch 20 adds a second" sentence).
**GREEN:** test passes.
**Validation:** `pytest tests/unit/domain/test_composition.py -v`
**Commit:** `feat(domain): add CompositionType.API_GATEWAY_LAMBDA_DYNAMODB`
**Security invariant:** none yet exercised (pure enum) — this is the one purely additive, risk-free task in the whole plan.
**Deterministic/offline.**

---

### Task 2: `ApiLambdaDynamoDbSpec` contract

**Files:** `src/iac_agent/compositions/api_lambda_dynamodb/__init__.py` (new), `src/iac_agent/compositions/api_lambda_dynamodb/contract.py` (new)
**Objective:** the exact contract from design §3 — `api: ApiGatewayResourceSpec`, `function: LambdaResourceSpec`, `route: RouteSpec` (imported from `api_lambda.contract`, not duplicated), `table: DynamoDBResourceSpec`, `composition_type: Literal["api_gateway_lambda_dynamodb"]`, pairwise-distinct-names validator (3-way), environment-consistency validator (3-way).
**Tests:** `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_contract.py` — construction success; name pattern/length rejection; each pairwise-name collision (api/function, api/table, function/table) rejected; environment mismatch (each of api/function/table) rejected; `composition_type` is the fixed literal; `route`/`HttpMethod` really are `iac_agent.compositions.api_lambda.contract`'s own classes (import-identity assertion, proving no duplication).
**RED:** module doesn't exist.
**Minimum implementation:** the contract, mirroring `ApiLambdaSpec`/`ServerlessWorkerSpec` validators exactly, extended to three sub-specs.
**GREEN:** all tests pass.
**Validation:** `pytest tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_contract.py -v`
**Commit:** `feat(compositions): add ApiLambdaDynamoDbSpec contract`
**Security invariant:** design invariant "distinct type, never a subclass of `ApiLambdaSpec`" — a dedicated test asserts `ApiLambdaDynamoDbSpec` is not a subclass of `ApiLambdaSpec` (`not issubclass(ApiLambdaDynamoDbSpec, ApiLambdaSpec)`), the mechanical proof underlying every later dispatch-safety claim.
**Deterministic/offline.**

---

### Task 3: `ApiLambdaDynamoDbTerraformRenderer`

**Files:** `src/iac_agent/compositions/api_lambda_dynamodb/renderer.py` (new)
**Objective:** render `main.tf`/`versions.tf` instantiating `api_gateway`+`lambda`+`dynamodb` trusted modules plus: the API-Gateway integration/route/Lambda-permission blocks (reused technique from `api_lambda/renderer.py`) and the DynamoDB write-scope `aws_iam_role_policy` block (reused technique from `serverless_worker/renderer.py`, action set = exactly `dynamodb:PutItem` per closed decision).
**Tests:** `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_renderer.py` — byte-level assertions (same style as the two existing renderer unit-test files): exactly one `aws_apigatewayv2_integration`/`aws_apigatewayv2_route`/`aws_lambda_permission`/`aws_iam_role_policy` block each; the IAM policy's `Action` is exactly `["dynamodb:PutItem"]` (never a list with more than one element, never a wildcard); `Resource` is scoped to `module.table`'s ARN output; `role = module.function.execution_role_name`; no raw `aws_apigatewayv2_api`/`aws_lambda_function`/`aws_iam_role`/`aws_dynamodb_table` block ever emitted; deterministic byte-identical output for the same spec (render twice, compare).
**RED:** module doesn't exist.
**Minimum implementation:** the renderer, composed from the two reused techniques.
**GREEN:** all tests pass.
**Validation:** `pytest tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_renderer.py -v`
**Commit:** `feat(compositions): add ApiLambdaDynamoDbTerraformRenderer`
**Security invariant:** design invariant "exactly `dynamodb:PutItem`, never broader" — directly tested here, at the string-rendering level, before any real Terraform is involved.
**Deterministic/offline.**

---

### Task 4: `compositions/resource.py` dispatch

**Files:** `src/iac_agent/compositions/resource.py`
**Objective:** widen `CompositionSpec` union; add `case ApiLambdaDynamoDbSpec(): return CompositionType.API_GATEWAY_LAMBDA_DYNAMODB` to `composition_type_of()`.
**Tests:** extend `tests/unit/compositions/test_resource.py` (or equivalent existing file) — `composition_type_of(ApiLambdaDynamoDbSpec(...))` returns exactly `API_GATEWAY_LAMBDA_DYNAMODB`, never `API_GATEWAY_LAMBDA`; **the core mis-dispatch regression**: construct an `ApiLambdaDynamoDbSpec`, assert `not isinstance(it, ApiLambdaSpec)`, and assert `composition_type_of(it) != CompositionType.API_GATEWAY_LAMBDA`.
**RED:** new case doesn't exist, `composition_type_of` raises `ValueError` for the new type.
**Minimum implementation:** one new `case` arm + union widening.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/compositions/ -v`
**Commit:** `feat(compositions): recognize ApiLambdaDynamoDbSpec in composition_type_of`
**Security invariant:** the single most important mis-classification regression test in this whole plan lives here — every later composition-policy/Checkov-profile lookup depends on this function returning the right enum.
**Deterministic/offline.**

---

### Task 5: `request.py` — `IacRequestSpec`/`IacRenderer` wiring

**Files:** `src/iac_agent/request.py`
**Objective:** widen `IacRequestSpec` union; add `api_lambda_dynamodb_renderer` optional constructor parameter to `IacRenderer.__init__` (defaulting to a fresh `ApiLambdaDynamoDbTerraformRenderer()`, exactly like the existing two composition-renderer parameters); add `case ApiLambdaDynamoDbSpec():` to `.render()`, resolving `api`/`function`/`table` module sources from `trusted_module_dirs`.
**Tests:** extend `tests/unit/test_request.py` (or equivalent) — `IacRenderer().render(ApiLambdaDynamoDbSpec(...), trusted_module_dirs=..., workspace=...)` returns a `GeneratedTerraformComposition` with the expected files; injected fake `api_lambda_dynamodb_renderer` is actually invoked (constructor-injection proof, mirroring the existing two renderers' own tests).
**RED:** `IacRenderer.render()` falls through to the `case _` single-resource path for the new type and raises (since `resource_type_of` doesn't recognize a composition spec).
**Minimum implementation:** the widened union + constructor param + new `case` arm.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/test_request.py -v` (or the actual existing filename — confirm at implementation time)
**Commit:** `feat: dispatch ApiLambdaDynamoDbSpec through IacRenderer`
**Security invariant:** confirms the `case _` fallback is never silently reached for the new composition (would otherwise call `resource_type_of` on a composition spec, an existing failure mode this design's §9 flagged).
**Deterministic/offline.**

---

### Task 6: `intent/resolver.py` — resolution + clarification

**Files:** `src/iac_agent/intent/resolver.py`
**Objective:** two new `match` arms (design §2) + `_build_api_lambda_dynamodb_spec()` helper, reusing `LAMBDA_DEFAULT_HANDLER`, `API_LAMBDA_DEFAULT_ROUTE`, `WORKER_DDB_DEFAULT_PARTITION_KEY` verbatim.
**Tests:** extend `tests/unit/intent/test_resolver.py` — `{API, SYNCHRONOUS, {HTTP_ENDPOINT, PERSISTENCE}}` resolves to `ApiLambdaDynamoDbSpec` with `matched_pattern="api+synchronous+http_endpoint+persistence"`; `{API, UNSPECIFIED, {HTTP_ENDPOINT, PERSISTENCE}}` returns `ClarificationRequired` for `interaction_pattern`; `{API, ASYNCHRONOUS, {HTTP_ENDPOINT, PERSISTENCE}}` still returns `UnsupportedArchitecture` (`UNSUPPORTED_COMBINATION`) — the explicit fail-closed proof; every existing resolver test for the other two compositions and for bare `{HTTP_ENDPOINT}`/worker/storage combinations re-run unmodified and green (backward-compat proof for the resolver specifically).
**RED:** the two new intents fall through to `UnsupportedArchitecture`/no clarification.
**Minimum implementation:** the two arms + builder function, placed after the existing `API_GATEWAY_LAMBDA` arm and its clarification counterpart.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/intent/test_resolver.py -v`
**Commit:** `feat(intent): resolve API+HTTP_ENDPOINT+PERSISTENCE to ApiLambdaDynamoDbSpec`
**Security invariant:** design invariant "LLM never selects resources" — this task is the only place `ArchitectureIntent` ever turns into a concrete spec; the test suite proves every unmapped combination remains fail-closed, not just the ones this batch cares about.
**Deterministic/offline.**

---

### Task 7: `persistence/checkpoints.py` — allowlist entry

**Files:** `src/iac_agent/persistence/checkpoints.py`
**Objective:** add `("iac_agent.compositions.api_lambda_dynamodb.contract", "ApiLambdaDynamoDbSpec")` to `_ALLOWED_WORKFLOW_TYPES`.
**Tests:** `tests/unit/persistence/test_checkpoints_allowed_types.py` (extend existing, if present, else new) — a direct, isolated serializer round-trip: build the real `JsonPlusSerializer` via `_build_serializer()`, serialize an `ApiLambdaDynamoDbSpec` instance, deserialize it, assert `type(result) is ApiLambdaDynamoDbSpec` (not `isinstance` — ruling out silent widening to a base/dict type). This is the narrow, fast, Gate-A-safe version of the proof; the full fresh-process graph-level proof is Task 18 (Gate B), which exercises the real interrupt/resume path end-to-end.
**RED:** the new type is not in the allowlist; serialization either raises or falls back to a permissive representation (exact failure mode depends on `JsonPlusSerializer`'s behavior for an unregistered type — captured as real RED evidence, not assumed).
**Minimum implementation:** the one new tuple entry.
**GREEN:** test passes.
**Validation:** `pytest tests/unit/persistence/ -v`
**Commit:** `fix(persistence): allow ApiLambdaDynamoDbSpec in the durable checkpoint serializer`
**Security invariant:** design's "critical dispatch boundary" — this is the isolated unit proof; Task 18 is the full integration proof. Both are mandatory, neither substitutes for the other.
**Deterministic/offline.**

---

### Task 8: `policies/composition.py` — policy IDs and evaluation

**Files:** `src/iac_agent/policies/composition.py`
**Objective:** five new policy-ID constants (design §7); new `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[API_GATEWAY_LAMBDA_DYNAMODB]` entry; new `case ApiLambdaDynamoDbSpec():` arm in `evaluate_composition_policies()`, combining three new `_evaluate_api_lambda_dynamodb_*` finding functions (invoke-permission, no-wildcard-principal, route-explicit — same evidence sources as `api_lambda`'s own, re-authored against the new spec type) with one new `_evaluate_api_lambda_dynamodb_write_scope_policy` (mirrors `_evaluate_dynamodb_write_scope_policy` exactly, asserting the message names `dynamodb:PutItem` and the table name only) plus the four reused-verbatim sub-policies (`evaluate_lambda_tracing_policy`, `evaluate_lambda_reserved_concurrency_policy`, `evaluate_dynamodb_pitr_policy`, `evaluate_dynamodb_deletion_protection_policy`) against `spec.function`/`spec.table`.
**Tests:** extend `tests/unit/policies/test_composition.py` — every new policy ID appears exactly once per evaluation, all `PASS` for a well-formed spec; `evaluate_composition_policies()` raises `ValueError` for no other spec type (unchanged `case _` behavior — regression proof); `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE` has exactly three keys now (backward-compat count assertion).
**RED:** `evaluate_composition_policies(ApiLambdaDynamoDbSpec(...), ...)` raises `ValueError` (falls to the existing `case _`).
**Minimum implementation:** IDs + dict entry + evaluator functions + `case` arm.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/policies/test_composition.py -v`
**Commit:** `feat(policies): add composition policies for API Gateway + Lambda + DynamoDB`
**Security invariant:** `TF_NO_DESTRUCTIVE_CHANGES` and the four reused Lambda/DynamoDB sub-policies are proven still wired in for the new composition — the same "don't silently discard existing evidence" discipline the design's §7 states verbatim for the first two compositions.
**Deterministic/offline.**

---

### Task 9: `graph/workflow.py` — presentation (PR body, commit message, centralized label)

**Files:** `src/iac_agent/graph/workflow.py`
**Objective:** one new module-level constant for the human-readable label (`"API Gateway + Lambda + DynamoDB"`, closed decision, defined once); new `case ApiLambdaDynamoDbSpec():` arm in `_pr_body()` (identity_lines: composition type, API, route, Lambda, table); new `case ApiLambdaDynamoDbSpec():` arm in the commit-message block, `resource_kind = "api lambda dynamodb"` (closed decision, exact string).
**Tests:** extend `tests/unit/graph/test_workflow_api_lambda_dynamodb.py` (new file) — `_pr_body()` output contains all four identity lines with the correct names for a constructed `ApiLambdaDynamoDbSpec` state; the commit-message-producing code path produces exactly `"api lambda dynamodb"`; existing `ServerlessWorkerSpec`/`ApiLambdaSpec` PR-body/commit-message tests re-run unmodified and green.
**RED:** both blocks fall through to their `case _` arm (`resource_type_of` raises for a composition spec).
**Minimum implementation:** the constant + two new `case` arms.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/graph/test_workflow_api_lambda_dynamodb.py -v`
**Commit:** `feat(graph): present ApiLambdaDynamoDbSpec in PR body and commit message`
**Security invariant:** PR body never emits raw Terraform/Checkov JSON or workspace paths — same existing invariant, re-verified for the new arm specifically (a new arm is exactly where a copy-paste mistake could leak something the existing arms don't).
**Deterministic/offline.**

---

### Task 10: `graph/workflow.py` — policy/Checkov/security-gate dispatch widening

**Files:** `src/iac_agent/graph/workflow.py`
**Objective:** widen the three grouped `case ServerlessWorkerSpec() | ApiLambdaSpec():` arms (in `platform_policy`, `checkov_scan`, `security_gate`) to `| ApiLambdaDynamoDbSpec()`; add `api_lambda_dynamodb_renderer` optional parameter to `build_iac_workflow()`, threaded into `IacRenderer(...)` construction.
**Tests:** extend `tests/unit/graph/test_workflow_api_lambda_dynamodb.py` — build a real (compiled, in-memory) graph via `build_iac_workflow` with fake terraform/checkov/source-control adapters; submit an `ApiLambdaDynamoDbSpec` request; assert `platform_policy` took the **composition** path (`evaluate_composition_policies` was called, proven via a spy/fake, not just output shape) and never the single-resource fallback; same proof for `checkov_scan` (`composition_checkov_profile_for` called) and `security_gate` (`required_policy_ids=` path taken, not `resource_type=`) — **this is the exact "grouped OR-arm forgotten" regression the design flagged**, tested directly rather than inferred from output alone.
**RED:** the new spec type falls through the grouped arms into each node's `case _` fallback, which calls `resource_type_of`/`checkov_profile_for` and raises or mis-classifies.
**Minimum implementation:** widen the three arms; add the constructor parameter.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/graph/ -v` (full graph unit suite — backward-compat proof for the other two compositions' equivalent tests in the same run)
**Commit:** `feat(graph): route ApiLambdaDynamoDbSpec through composition policy/Checkov/security-gate dispatch`
**Security invariant:** this is the highest-leverage regression task in Gate A — a missed widening here would mean the new composition's security gate silently evaluates the wrong (or no) required policies.
**Deterministic/offline.**

---

### Task 11: `cli/present.py` — label and component presentation

**Files:** `src/iac_agent/cli/present.py`
**Objective:** new `isinstance(spec, ApiLambdaDynamoDbSpec)` branch in `_architecture_label()` (returning the centralized label, imported from `graph/workflow.py` or a shared constants location — decided at implementation time, not a new registry) placed **before** the unconditional fallback; new branch in `_component_lines()` listing `api`/`route`/`function`/`table`.
**Tests:** extend `tests/unit/cli/test_present.py` — `_architecture_label(ApiLambdaDynamoDbSpec(...))` returns the new label and is explicitly asserted **not equal to `"s3"`**; `_component_lines(...)` contains all four lines (api, route, function, table); existing S3/serverless-worker/api-lambda label/component tests re-run unmodified and green.
**RED:** `_architecture_label()` returns `"s3"` for the new spec (the exact pre-existing sharp edge found during design).
**Minimum implementation:** the two new branches.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/cli/test_present.py -v`
**Commit:** `fix(cli): present ApiLambdaDynamoDbSpec instead of the s3 fallback`
**Security invariant:** none security-relevant, but this is the mandatory non-degradation regression the design explicitly locked — treated with the same rigor as a security test.
**Deterministic/offline.**

---

### Task 12: Backward-compatibility regression checkpoint

**Files:** none (no production code change)
**Objective:** prove Tasks 1–11 changed nothing about `ServerlessWorkerSpec`/`ApiLambdaSpec` behavior.
**Validation:** full `pytest tests/unit -v` (all ~1400+ tests, including every existing composition #1/#2 test, unmodified) and a diff review confirming no existing test file's assertions were edited (only new tests added) except where a task explicitly extended an existing file with new cases (Tasks 1, 4, 6, 8, 9, 10, 11 — each additive only).
**Commit:** none (checkpoint only; if this surfaces a regression, the fix is a new commit against the offending task, not a retroactive edit to this checkpoint).
**Security invariant:** design invariant "compositions #1 and #2 remain behaviorally unchanged" — this is the explicit, dedicated proof point, not an assumption carried forward from individual task-level tests.
**Deterministic/offline.**

---

### Task 13: Golden-eval dataset, loader, runner, evaluator

**Files:** `evals/datasets/api_lambda_dynamodb_golden.json` (new), `evals/scenarios/api_lambda_dynamodb_loader.py` (new), `evals/scenarios/api_lambda_dynamodb_runner.py` (new), `evals/evaluators/api_lambda_dynamodb.py` (new)
**Objective:** mirror `api_lambda`'s dataset/loader/runner/evaluator shape exactly, extended with `table_name`/`point_in_time_recovery`/`deletion_protection` expected fields (mirroring how `serverless_worker`'s own dataset extended `sqs`'s shape) — at least one valid scenario and one invalid (fails construction) scenario, matching the minimum shape every existing dataset already has.
**Tests:** `tests/unit/evals/test_api_lambda_dynamodb_loader.py` (new, mirrors the existing loader test files exactly) — malformed dataset rejection, duplicate-id rejection, required-key-when-valid enforcement.
**RED:** modules/dataset don't exist.
**Minimum implementation:** the four new files, offline/JSON+Python only.
**GREEN:** tests pass.
**Validation:** `pytest tests/unit/evals/ -v`
**Commit:** `feat(evals): add API Gateway + Lambda + DynamoDB golden dataset and loader`
**Security invariant:** none new — this task only prepares the fixtures Gate B's real-tool golden-eval test (Task 17) will actually execute.
**Deterministic/offline.**

---

### Task 14: Documentation

**Files:** `docs/compositions/api-lambda-dynamodb.md` (new, mirrors `docs/compositions/api-lambda.md`'s structure: architecture diagram-in-prose, contract summary, IAM design rationale, Checkov profile section — filled in only after Task 16 produces the real profile, so this file is drafted here with a placeholder note and completed/amended in Task 16's own commit), `docs/roadmap.md` (new "Phase 2 — API Gateway + Lambda + DynamoDB (composition)" section, following the existing Batch 19/20 section format exactly), `README.md` (one new doc-list sentence, same pattern as every prior addition).
**Tests:** none new (no existing test pattern checks composition doc cross-references — confirmed absent from the current test suite during design).
**Minimum implementation:** the three doc edits.
**Validation:** manual read-through for consistency with Tasks 1–13's actual final shape; `ruff check .` (docs aren't linted, but this validates nothing was accidentally broken in any `.py` file touched this session).
**Commit:** `docs: document the API Gateway + Lambda + DynamoDB composition`
**Security invariant:** none.
**Deterministic/offline.**

---

## Gate B — real Terraform + Checkov (credential-free)

### Task 15: Real Terraform validation of the renderer

**Files:** `tests/integration/test_api_lambda_dynamodb_renderer_terraform.py` (new, `real_tool`-marked, mirrors `test_api_lambda_renderer_terraform.py`/`test_serverless_worker_renderer_terraform.py` exactly)
**Objective:** real `terraform fmt`/`init`/`validate`/`plan`/`show_json` against the rendered composition, credential-free (skip-flags, fake env vars — same technique every existing renderer-terraform test uses), asserting the plan's `resource_changes` are exactly the expected managed resources (module-internal resources from all three trusted modules + the composition-owned integration/route/permission/IAM-policy resources), all `actions == ["create"]`.
**RED:** doesn't exist / renderer output isn't yet real Terraform (would have already been caught by Task 3, but this is the first *real* Terraform-binary proof, not string assertions).
**Minimum implementation:** the test only (renderer already exists from Task 3).
**GREEN:** test passes against the real `terraform` binary.
**Validation:** `pytest tests/integration/test_api_lambda_dynamodb_renderer_terraform.py -q -m real_tool`
**Commit:** `test(compositions): prove ApiLambdaDynamoDbTerraformRenderer output is valid, real Terraform`
**Security invariant:** confirms the IAM policy JSON Task 3 only string-asserted actually parses and plans as real Terraform with exactly the intended `dynamodb:PutItem`-only action — the first point this claim is checked by the real tool rather than by string matching.
**Real tool, credential-free.**

---

### Task 16: Empirical Checkov profile discovery (its own dedicated gate)

**Files:** `src/iac_agent/security/composition_checkov_profiles.py` (new entry), `tests/unit/security/test_composition_checkov_profiles.py` (extend — frozen skip-list regression test), `docs/compositions/api-lambda-dynamodb.md` (amended with the real, evidence-cited skip list, completing Task 14's placeholder)
**Objective:** execute the exact 8-step procedure from design §8, for real:
1. Render a real, secure-default `ApiLambdaDynamoDbSpec` composition.
2. Run the existing strict real-tool Checkov path against it with **zero** composition-specific skips.
3. Capture the actual reported findings (recorded verbatim in the commit message and the doc, exactly like the existing two profiles' own module-docstring evidence).
4. Evaluate each finding individually — is it a legitimate carry-forward of an already-approved skip (cite which), or genuinely new (requires a fresh, explicit decision — **stop and ask**, do not decide unilaterally, if this occurs)?
5. Add only the empirically justified skips.
6. Freeze the resulting profile as the new `CompositionType.API_GATEWAY_LAMBDA_DYNAMODB` entry.
7. Add a regression test asserting the frozen skip list matches exactly (no silent future drift).
8. Re-run the strict scan with only the frozen skips applied and prove it passes.
**RED:** no profile entry exists yet; `composition_checkov_profile_for(API_GATEWAY_LAMBDA_DYNAMODB)` raises `KeyError`.
**Minimum implementation:** the profile entry, derived only from real, captured evidence — never from unioning the other two profiles (explicit prohibition, re-stated here as an implementation-time guardrail, not just a design-time one).
**GREEN:** the frozen-list regression test and the final strict-scan-passes test both pass.
**Validation:** `pytest tests/unit/security/test_composition_checkov_profiles.py -v` + `pytest tests/integration/test_api_lambda_dynamodb_renderer_terraform.py -q -m real_tool` (re-run, now with the real Checkov step included if that test is extended to also scan, or a dedicated Checkov-only real-tool test — exact split decided at implementation time, following whichever of the two existing compositions' own test-file split is cleaner to mirror)
**Commit:** `feat(security): freeze empirically-derived Checkov profile for API Gateway + Lambda + DynamoDB`
**Security invariant:** design invariant "never a union" — the commit message itself must state the real, captured finding count and exactly which skips were newly justified vs. carried forward, mirroring the existing two profiles' own documented evidence trail.
**Real tool, credential-free.**

---

### Task 17: Golden real-tool evaluation

**Files:** `tests/integration/test_api_lambda_dynamodb_golden_evals.py` (new), `tests/integration/test_api_lambda_dynamodb_golden_real_tool_eval.py` (new) — mirror the existing two compositions' equivalent pairs exactly.
**Objective:** run every scenario in Task 13's golden dataset through the real resolver → renderer → Terraform → Checkov → security-gate pipeline, asserting each scenario's `expected` outcome (including `overall_security_status`) matches.
**RED:** doesn't exist.
**Minimum implementation:** the two test files, exercising already-implemented production code only (no new production code this task).
**GREEN:** tests pass.
**Validation:** `pytest tests/integration/test_api_lambda_dynamodb_golden_evals.py tests/integration/test_api_lambda_dynamodb_golden_real_tool_eval.py -q -m real_tool`
**Commit:** `test(compositions): prove API Gateway + Lambda + DynamoDB golden scenarios end-to-end`
**Security invariant:** end-to-end proof that Tasks 1–16 compose correctly, not just pass in isolation.
**Real tool, credential-free.**

---

### Task 18: Durable HITL reconstruction/resume proof (mandatory, closed decision)

**Files:** `tests/integration/test_api_lambda_dynamodb_workflow_persistence.py` (new, mirrors `test_serverless_worker_workflow_persistence.py`/`test_api_lambda_workflow_persistence.py` exactly, `real_tool`-marked since reaching the interrupt requires real terraform/checkov)
**Objective:** submit an `ApiLambdaDynamoDbSpec` request through the real compiled graph to the HITL interrupt, using a real, on-disk SQLite checkpointer (`open_sqlite_checkpointer`, real file path, not `:memory:`); close that checkpointer/graph entirely; **open a fresh `open_sqlite_checkpointer` call against the same database path** (simulating a real process restart, not just re-reading within the same Python process); reconstruct the paused state via the fresh checkpointer; assert `type(reconstructed_state["resource_spec"]) is ApiLambdaDynamoDbSpec` exactly (not `isinstance`); assert it is explicitly not `ApiLambdaSpec`, not an `AWSResourceSpec`, not a raw `dict`; resume with `ApprovalDecision.APPROVE` through to `source_control` (using a fake `SourceControlPort`, per existing convention) and assert a `pull_request` result is produced, proving the full round trip.
**RED:** without Task 7's allowlist entry, this test fails at the reconstruction step (exact failure mode captured as real RED evidence — either a raised deserialization error or, worse, a silently degraded type, which is exactly why the `type(...) is` assertion is mandatory rather than `isinstance`).
**Minimum implementation:** the test only — Task 7 already provides the allowlist entry; this task proves it under real, end-to-end, fresh-process conditions.
**GREEN:** test passes.
**Validation:** `pytest tests/integration/test_api_lambda_dynamodb_workflow_persistence.py -q -m real_tool`
**Commit:** `test(compositions): prove ApiLambdaDynamoDbSpec survives a real fresh-process HITL resume`
**Security invariant:** the design's own explicitly-locked mandatory invariant — durable HITL behavior remains unchanged for the two existing compositions, and correctly extends to the third, proven under a real process-restart simulation, not merely a same-process round-trip.
**Real tool, credential-free.**

---

### Task 19: Full regression gate and closure report

**Files:** none (checkpoint only)
**Objective:** run everything, together, one last time, before declaring Batch 26 implementation complete.
**Validation:**
- `pytest tests/unit -q` (full deterministic suite)
- `pytest tests/integration -q -m "not real_aws_plan and not real_llm"` **scoped explicitly to this batch's own new files plus the existing composition #1/#2 integration files** (not the entire `tests/integration` directory — Batch 25's own closure report already noted an unrelated, network-dependent `real_tool` test elsewhere in this directory that can stall; this task's validation command must name the specific files/patterns it runs, not `tests/integration` unqualified)
- `ruff check .`
- `terraform fmt -check -recursive terraform/modules` (unchanged modules — confirms no accidental edit)
- `git diff --check`
- Negative-space checks: no `terraform apply`/`destroy` introduced anywhere in the new files; no static AWS credentials; no new remote-state configuration.
**Commit:** none (or a final no-op "batch 26 complete" doc note, if the human wants one — not assumed here).
**Security invariant:** every invariant listed across Tasks 1–18, re-confirmed together in one pass.
**Deterministic + real-tool combined checkpoint.**

---

## Report

1. **Design path:** `docs/superpowers/specs/2026-09-27-api-lambda-dynamodb-composition-design.md`
2. **Plan path:** this file.
3. **Task count:** 19 (14 Gate A, 4 Gate B, 1 closure checkpoint).
4. **Planned production files:** `domain/composition.py`; `compositions/api_lambda_dynamodb/{__init__,contract,renderer}.py` (new); `compositions/resource.py`; `request.py`; `intent/resolver.py`; `persistence/checkpoints.py`; `policies/composition.py`; `graph/workflow.py`; `cli/present.py`; `security/composition_checkov_profiles.py`.
5. **Planned test/eval files:** `tests/unit/domain/test_composition.py` (extend); `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_{contract,renderer}.py` (new); `tests/unit/compositions/test_resource.py` (extend); request/resolver/persistence/policies unit test files (extend); `tests/unit/graph/test_workflow_api_lambda_dynamodb.py` (new); `tests/unit/cli/test_present.py` (extend); `evals/datasets/api_lambda_dynamodb_golden.json` + `evals/scenarios/api_lambda_dynamodb_{loader,runner}.py` + `evals/evaluators/api_lambda_dynamodb.py` (new); `tests/unit/evals/test_api_lambda_dynamodb_loader.py` (new); `tests/integration/test_api_lambda_dynamodb_{renderer_terraform,golden_evals,golden_real_tool_eval,workflow_persistence}.py` (new, Gate B); `tests/unit/security/test_composition_checkov_profiles.py` (extend).
6. **Gate structure:** Gate A (Tasks 1–14, deterministic/offline, auto-runnable once authorized) → Gate B (Tasks 15–18, real Terraform+Checkov, still credential-free) → Task 19 (closure checkpoint). No Gate C/D/E — this batch never touches real AWS, GitHub writes, or OpenAI.
7. **Commit boundaries:** one commit per task exactly as specified above (18 commits; Task 19 is a checkpoint, not a commit, unless a regression fix is needed, in which case that fix is its own new commit against the responsible task, never a retroactive edit).
8. **Human-authorization boundary:** the whole plan is deterministic-or-credential-free — unlike Batch 25, there is no point in this sequence that inherently requires a separate mid-execution authorization message the way "Gate C" did for real GitHub OIDC writes. A single "authorize Gate A" and, once that's reviewed, a single "authorize Gate B" message (mirroring this repository's own established two-step rhythm) is sufficient; this plan does not assume blanket authorization for both gates at once.
9. **Recommended execution mode:** inline, sequential, same discipline as every prior batch — no subagent parallelization (each task depends on the shape of the previous one; nothing here is embarrassingly parallel).

Do not implement any task from this plan without further instruction.

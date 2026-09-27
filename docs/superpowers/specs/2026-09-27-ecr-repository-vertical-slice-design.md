# Batch 27 — ECR Repository vertical slice (design)

Discovery base: `origin/main` `037edf6` (PR #9, Batch 26's third
composition, merged 2026-09-27). The design branch is
`docs/batch27-ecr-repository-design`. HEAD at closure is `96200b6`,
which is `037edf6` plus the initial design commit only — no production
implementation exists on this branch. Closure re-read the
implementation at that baseline (enums, resolver, dispatch, serializer
allowlist, workflow, policies, CLI, Checkov profiles, golden datasets,
Terraform modules, and `.github/workflows/ci.yml`) and corrected the
interrupted draft where it contradicted that code. Design-only: no
implementation, no `terraform apply`/`destroy`, no AWS credentials, no
AWS/OpenAI call, no GitHub mutation. Batch 25's deferred
AWS-plan-boundary Tasks 12–16 and Batch 26 are untouched throughout.

## 0. Purpose (per the authorization — read this before the rest)

This batch has two deliverables, not one: (a) a minimal, honest ECR
design, and (b) a measured friction inventory to answer the Batch 28
registry question with evidence, not aesthetics. Section 15/16/17
carry the actual evidence; sections 1–14 carry the design that
generates it.

## 1. Current-state evidence

Re-discovered against current `main`, not assumed from Batch 26's own
design doc (which only enumerated *composition* dispatch sites — a
standalone resource's registration surface is a different, smaller,
independently-verified list, below).

### 1.1 Domain models

- `iac_agent.domain.resource.ResourceType` — a flat `StrEnum`, five
  members today: `SQS, S3, DYNAMODB, LAMBDA, API_GATEWAY`
  ([domain/resource.py](src/iac_agent/domain/resource.py)).
- `iac_agent.domain.composition.CompositionType` — three members
  (Batch 19/20/26). Not relevant to a standalone-resource design
  unless §3 concludes ECR should be a composition (it doesn't — see
  §3).

### 1.2 `ArchitectureIntent` vocabulary (Batch 21, unchanged since)

`intent/models.py`: `WorkloadType {API, WORKER, STORAGE, UNSPECIFIED}`,
`InteractionPattern {SYNCHRONOUS, ASYNCHRONOUS, UNSPECIFIED}`,
`Capability {HTTP_ENDPOINT, QUEUE_PROCESSING, PERSISTENCE,
OBJECT_STORAGE}` — exactly four members, with an explicit docstring
warning that a fifth (`BACKGROUND_PROCESSING`) was evaluated and
rejected because "no allowlist row's outcome ever depends on it."
`AwsServiceHint {SQS, S3, DYNAMODB, LAMBDA, API_GATEWAY}` — a *separate*,
non-authoritative enum, never read by the resolver, existing purely so
an LLM can name a hint for observability.

No member of any of these four enums names or implies a container
registry today. Confirmed by direct grep (`aws_ecr`, `ECR_REPO`,
`ecr_repository`, word-boundary `\bECR\b`) across the entire repository
(`*.py`, `*.tf`, `*.md`, `*.json`): **zero matches**. This is a
genuinely new resource, not a rename or an existing-but-unwired
concept.

### 1.3 Resolver (`intent/resolver.py`)

`ArchitectureResolver.resolve()` is a single closed `match` over
`(workload_type, interaction_pattern, capabilities)`, four resolved
rows today (`api_lambda`, `api_lambda_dynamodb`, `serverless_worker`,
`storage+object_storage → S3ResourceSpec`), four clarification arms
(`WorkloadType.UNSPECIFIED`, plus one `interaction_pattern`
clarification for each of the API, API+persistence, and worker resolved
rows — `STORAGE` has none), and a fail-closed `case _` classifying
everything else as `UnsupportedArchitecture` (`UNSUPPORTED_CAPABILITY`
specifically for any unmapped `STORAGE`-workload combination,
`UNSUPPORTED_COMBINATION` otherwise — see `_classify_unsupported`).

The only existing "wrong capability under STORAGE" regression test
(`test_storage_wrong_capability_set_returns_unsupported_capability`,
and its golden-dataset twin `storage_wrong_capability_unsupported_capability`)
uses `{PERSISTENCE}`, never a new capability — confirmed non-conflicting
with any additive `Capability` member (§4).

### 1.4 Request/resource dispatch

`providers/aws/resource.py`: `AWSResourceSpec` is a plain 5-member
`Literal`-style union; `resource_type_of()` is a closed `match`,
fail-closed `raise ValueError` default. Its own docstring states the
extension contract exactly: "Adding a new resource type means adding
one member to `ResourceType`, one arm to `AWSResourceSpec`, and one
`case` here — not a new abstraction layer."

`request.py`'s `IacRequestSpec`/`IacRenderer` widens this further for
*compositions* only — a standalone resource never touches
`request.py` at all (confirmed: `IacRenderer.render()`'s `case _` arm
already forwards any `AWSResourceSpec` to the generic
`AWSResourceRenderer`, unchanged since Batch 16).

### 1.5 `IacRenderer` / `AWSResourceRenderer`

`providers/aws/renderer.py`'s `AWSResourceRenderer` dispatches on the
same five-member union via constructor-injected per-resource renderers,
each defaulting to a real concrete renderer — the exact pattern every
new resource type has followed since Batch 16.

### 1.6 Persistence / checkpoint serialization

`persistence/checkpoints.py`'s `_ALLOWED_WORKFLOW_TYPES` is a flat,
exhaustive `(module, qualname)` tuple list. **Every** concrete Pydantic
type reachable through `WorkflowState.resource_spec` is listed
individually, including nested enums (e.g. `LambdaRuntime`,
`LambdaArchitecture`, `LambdaTracingMode`, `DynamoDBKeyType`,
`DynamoDBBillingMode`). This is the exact mechanism Batch 26 proved can
silently degrade an unregistered type into a raw `dict` rather than
raising — confirmed as real, not theoretical, in that batch's own Task
7 RED evidence.

### 1.7 Workflow graph

`graph/workflow.py` has **zero** `match`/`case` branches on individual
`ResourceType` values anywhere in its node functions — every
resource-type-specific behavior is expressed as a `dict[ResourceType,
X]` lookup, not inline branching:
`_DEFAULT_TRUSTED_MODULE_DIRS`, `_RESOURCE_KIND_DISPLAY_NAMES`. Compare
this to the *composition*-side code in the same file, which has five
literal `case ServerlessWorkerSpec() | ApiLambdaSpec() | ...` branches
— standalone-resource dispatch is structurally simpler and already
closer to "table-driven" than composition dispatch. This is directly
relevant evidence for §17.

### 1.8 Policies

`policies/platform.py`: `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE`
(a `dict[ResourceType, tuple[str,...]]`) plus `evaluate_platform_policies()`,
a `match` over the same five concrete spec types, fail-closed. Existing
naming convention confirmed: `<RESOURCE>_<PROPERTY>_REQUIRED` for a
hard invariant (the constructible state always PASSes, because the
contract rejects the insecure value — the evaluator still keeps a
BLOCK branch for defense in depth, as SQS/S3/DynamoDB do — e.g.
`S3_ENCRYPTION_REQUIRED`, `DDB_ENCRYPTION_REQUIRED`), `<RESOURCE>_<PROPERTY>_RECOMMENDED` for a
caller-toggleable setting that WARNs when disabled (e.g.
`DDB_PITR_RECOMMENDED`, `S3_VERSIONING_RECOMMENDED`).

### 1.9 Checkov

`security/checkov_profiles.py`: same `dict[ResourceType,
CheckovScanProfile]` shape, each skip list empirically derived and
individually justified (module docstring, S3 example: "resource_count=5,
passed=13, failed=4 ... every skip below states an architectural scope
reason, never 'skip because Checkov fails'").

### 1.10 CLI presentation — a live, pre-existing bug this design exposes

`cli/present.py`'s `_architecture_label()`:

```python
def _architecture_label(spec: IacRequestSpec) -> str:
    if isinstance(spec, ServerlessWorkerSpec): return "serverless_worker"
    if isinstance(spec, ApiLambdaDynamoDbSpec): return "..."
    if isinstance(spec, ApiLambdaSpec): return "api_lambda"
    return "s3"
```

The fallback `return "s3"` fires for **every** non-composition spec —
today that means every standalone `AWSResourceSpec`
(`SQSResourceSpec`, `S3ResourceSpec`, `DynamoDBResourceSpec`,
`LambdaResourceSpec`, `ApiGatewayResourceSpec` — the resolver just
happens to only ever *resolve* `S3ResourceSpec` standalone today, so
the bug has never been observed, not because it doesn't exist). This
is the exact same class of sharp edge Batch 26 found and fixed for
compositions, now confirmed to exist independently for standalone
resources, currently masked by coincidence rather than correctness.
**Adding ECR as a second resolver-reachable standalone resource
type would immediately expose it** unless fixed as part of this
batch.

### 1.11 Golden-eval architecture

Confirmed one dataset + loader + runner + evaluator quartet per
resource type (`evals/{datasets,scenarios,evaluators}/s3_*`,
`dynamodb_*`, etc.), plus, per resource type: a real-tool renderer-
terraform test, a real-tool golden-eval test, and a real-tool
fresh-process workflow-persistence test
(`tests/integration/test_{s3,dynamodb,lambda,sqs}_{renderer_terraform,
golden_real_tool_eval,workflow_persistence}.py` — confirmed present
for all four existing standalone resource types; `api_gateway` has a
`renderer_terraform` test but **no** `workflow_persistence` test,
since it is never resolved standalone — direct evidence that this
per-type test suite exists exactly for resolver-reachable standalone
types).

### 1.12 Terraform modules

`terraform/modules/{sqs,s3,dynamodb,lambda,api_gateway}/` — each
`{main,variables,outputs,versions}.tf`. **No `ecr` module exists.**

### 1.13 Real AWS provider schema for `aws_ecr_repository` (verified, not assumed)

Verified directly via `terraform providers schema -json` against the
real `hashicorp/aws ~> 6.0` provider (credential-free — schema
inspection requires no AWS account, only the provider binary):

| Attribute | Shape |
|---|---|
| `name` | required string |
| `image_tag_mutability` | optional string (AWS default `MUTABLE` if omitted) |
| `image_scanning_configuration` | optional nested block, `scan_on_push` (bool, **required within the block**) |
| `encryption_configuration` | optional nested block, `encryption_type` (`AES256`\|`KMS`, AWS default `AES256`), `kms_key` (optional) |
| `force_delete` | optional bool (default false) |
| `image_tag_mutability_exclusion_filter` | optional nested block (newer feature) |
| computed outputs | `arn`, `id`, `registry_id`, `repository_url` |

Unlike S3 (which needs four separate sidecar resources —
`aws_s3_bucket_versioning`, `..._server_side_encryption_configuration`,
`..._public_access_block`, `..._policy`), ECR's scanning and encryption
settings are **inline nested blocks on the single `aws_ecr_repository`
resource** — the trusted module needs exactly one managed resource,
structurally closer to DynamoDB's single-resource-with-nested-blocks
module than to S3's four-resource module.

## 2. ECR domain model — CLOSED

```python
class EcrImageTagMutability(StrEnum):
    MUTABLE = "MUTABLE"
    IMMUTABLE = "IMMUTABLE"
    # MUTABLE_WITH_EXCLUSION / IMMUTABLE_WITH_EXCLUSION deliberately
    # excluded — see §12 non-goals (needs the exclusion-filter block).

class EcrEncryptionSpec(BaseModel):
    """Same invariant as SQS EncryptionSpec, S3EncryptionSpec, and
    DynamoDBEncryptionSpec: enabled=False is unconstructible.

    The default alone does not enforce that. Each of those models uses
    a field_validator that rejects False. EcrEncryptionSpec does too.

    CLOSED DECISION: no kms_key_id field — DynamoDBEncryptionSpec's
    shape, not S3EncryptionSpec's. Batch 27 supports only AWS-managed
    AES256. Customer-managed KMS is a future, separately designed
    capability. No speculative field is added now.
    """
    enabled: bool = True

    @field_validator("enabled")
    @classmethod
    def _enabled_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "encryption.enabled cannot be False — Batch 27 does not "
                "support an unencrypted repository"
            )
        return value

class EcrResourceSpec(BaseModel):
    resource_type: Literal["ecr_repository"] = "ecr_repository"
    name: str  # ECR-specific naming rules — see below, NOT copy-pasted
               # from SQS/S3's regex.
    environment: str | None = None
    image_tag_mutability: EcrImageTagMutability = EcrImageTagMutability.IMMUTABLE
    scan_on_push: bool = True
    encryption: EcrEncryptionSpec = Field(default_factory=EcrEncryptionSpec)
    tags: dict[str, str] = Field(default_factory=dict)
```

**Naming validator — cannot reuse an existing pattern verbatim, and now
verified word-for-word against AWS's own `CreateRepository` API
reference** (fetched directly, not assumed from general knowledge):

> Pattern: `[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*`
> Length: 2–256 characters.

This is not the same pattern as any existing contract. Re-read from
the current modules, the existing validators are:

- SQS: `^[A-Za-z0-9_-]+$`
- Lambda and API Gateway: `^[a-zA-Z0-9_-]+$`
- DynamoDB: `^[a-zA-Z0-9_.-]+$` (allows `.`)
- S3: `^[a-z0-9][a-z0-9.-]*[a-z0-9]$` (lowercase, allows `.`, forbids
  `_` and `/`)

None of them accepts ECR's `/` path segments, `__`, or `-+` separator
runs, and several of them allow uppercase, which ECR forbids. A new,
ECR-specific validator is required. Anchor the published pattern with
`^` and `$`, and enforce length 2–256 separately — the published
pattern does not encode the length bound.

**Discrepancy noted, not silently resolved:** AWS's own prose on the
same page says the name "must start with a letter", but the
documented regex itself (`[a-z0-9]+...`) permits a leading digit. The
regex is what the API actually enforces (it's the literal
`InvalidParameterException` validation source), so the Pydantic
validator should follow the regex, not the prose — flagged here so
implementation doesn't have to rediscover this inconsistency, and so a
real-tool test can confirm which one `terraform plan`'s own provider-
side validation (if any) actually enforces before treating this as
fully closed.

`resolve_base_name`/`component_name`'s own output (lowercase-hyphenated,
no path segments) already satisfies this pattern with no changes
needed there — a request never needs `/`-namespacing to be
constructible, though the contract's own name field accepts it if a
caller supplies one directly (non-LLM-constructed callers only, same
as every other resource).

**Also verified from the same API reference (new information, not in
the Terraform-schema-only view):** AWS's own documentation states
`imageScanningConfiguration` (the per-repository `scan_on_push` field)
"is being deprecated, in favor of specifying the image scanning
configuration at the registry level" via a separate
`PutRegistryScanningConfiguration`/`aws_ecr_registry_scanning_
configuration` resource. The Terraform provider's `aws_ecr_repository.
image_scanning_configuration` attribute is still fully present and
functional in the current schema (§1.13). This is a forward-looking
AWS direction, not a Batch 27 blocker. It is recorded as a future
pressure test (§19, §22). Batch 27 uses the per-repository field.
Registry-level scanning configuration is out of scope (§19).

`scan_on_push` and `image_tag_mutability` are ordinary, caller-toggleable
fields with safe defaults (mirroring `DynamoDBResourceSpec.
point_in_time_recovery`/`deletion_protection` exactly) — disabling
either is a legitimate, WARN-flagged choice, not construction-time
rejected. `encryption.enabled` is a hard invariant (mirroring SQS/S3/
DynamoDB's own `EncryptionSpec` pattern) — there is no way to construct
an `EcrResourceSpec` representing an unencrypted repository at all.

## 3. Standalone-resource vs. composition decision — CLOSED

**Decision: Option A — a standalone resource (`ResourceType.ECR`), not
a `CompositionType`, not an extension of an existing abstraction.**
Accepted exactly as recommended, on the repository's own distinction:
a composition models a *relationship* between multiple resources; ECR
is one independently managed resource.

Evaluated against actual repository evidence, not the requester's own
terminology:

- **Against "composition" (Option B):** `CompositionType`
  (`domain/composition.py`) explicitly classifies "a bounded,
  deterministic *relationship* between several already-supported
  resource types" — its own docstring states there is deliberately no
  `ResourceType.SERVERLESS` because "a composition is not itself a new
  kind of AWS resource." An ECR repository is exactly one AWS resource
  with no cross-resource relationship to render (no event source
  mapping, no IAM binding to a Lambda, no API Gateway route) — it does
  not fit this project's own definition of composition at all.
- **Against "extension of OBJECT_STORAGE" (Option C):** rejected
  explicitly — `Capability.OBJECT_STORAGE` is defined and consumed
  (via `AwsServiceHint.S3` precedent, and the resolver's own
  `"storage+object_storage"` matched-pattern string) as blob/file
  storage semantics (S3), not container image registry semantics.
  Reusing it would be exactly the "silently reinterpret an existing
  capability" the authorization explicitly forbids — a container
  registry is not object storage from a user's or an LLM's honest
  point of view, even though both eventually render to an S3-adjacent
  or ECR AWS API. `AwsServiceHint` is non-authoritative and would gain
  its own new `ECR` member instead (§4).
- **Option A fits directly:** every existing standalone resource
  (`SQS`, `S3`, `DYNAMODB`, `LAMBDA`, `API_GATEWAY`) is exactly "one
  AWS resource type, one trusted module, one contract" — ECR matches
  this shape precisely, and the *entire* registration-site inventory
  in §15 is a direct, evidenced re-application of that existing
  pattern, not a new one.

## 4. `ArchitectureIntent` mapping analysis — CLOSED

**Decision: approved exactly as proposed.** `Capability.CONTAINER_
REGISTRY`, reusing `WorkloadType.STORAGE` unchanged, `OBJECT_STORAGE`
never reinterpreted.

**Exact intent tuple:**

```python
workload_type       = WorkloadType.STORAGE
interaction_pattern = <any — resolved regardless, see below>
capabilities        = frozenset({Capability.CONTAINER_REGISTRY})
```

**Exact resolver arm and precedence** (re-verified against current
`intent/resolver.py` on `main` `037edf6`, not assumed): the existing
`STORAGE` row has **no** `interaction_pattern` guard at all —

```python
case WorkloadType.STORAGE if capabilities == frozenset({Capability.OBJECT_STORAGE}):
    return ResolvedArchitecture(
        request_spec=_build_s3_spec(intent, request_id=request_id),
        matched_pattern="storage+object_storage",
    )
```

— confirmed by the existing parametrized test
`test_storage_object_storage_resolves_to_s3_spec_regardless_of_
interaction_pattern` (SYNCHRONOUS/ASYNCHRONOUS/UNSPECIFIED all
resolve identically). The new ECR arm mirrors this exactly, **no
clarification arm needed** (unlike the `API`/`WORKER` rows, `STORAGE`
never asks about `interaction_pattern` at all — there is nothing to
clarify):

```python
case WorkloadType.STORAGE if capabilities == frozenset({Capability.CONTAINER_REGISTRY}):
    return ResolvedArchitecture(
        request_spec=_build_ecr_spec(intent, request_id=request_id),
        matched_pattern="storage+container_registry",
    )
```

Placement relative to the existing `OBJECT_STORAGE` arm is
irrelevant to correctness (exact-frozenset-equality guards on two
different single-member sets can never both match the same intent) —
placed directly after it for readability, mirroring this file's own
established convention.

**Confirmed: does not broaden any other `STORAGE` combination.**
`_classify_unsupported()`'s blanket "any unmapped `STORAGE` combination
→ `UNSUPPORTED_CAPABILITY`" rule is unchanged; the new arm only adds
one more *specific*, exact-set match before that fallback — every
other `STORAGE` capability set (including the existing
`test_storage_wrong_capability_set_returns_unsupported_capability`
test's `{PERSISTENCE}`) still falls through to it unchanged.

**Effects, explicitly:**

- **LLM interpretation:** one new closed-vocabulary word
  (`container_registry`). `_ResponsePayload` in
  `intent/adapters/openai.py` types `capabilities: list[Capability]`
  and `user_provided_hints: list[AwsServiceHint]`, so the structured-
  output schema widens automatically when those enums grow. There is
  no separate schema file to redesign. The hand-written `_INSTRUCTIONS`
  string does not widen automatically: it currently describes storage
  as object storage only, and it lists hintable services as SQS, S3,
  DynamoDB, Lambda, and API Gateway. Leaving that prose unchanged
  would teach the model to call a container registry `object_storage`,
  which the resolver would then correctly turn into S3. Batch 27
  therefore adds a minimal orthogonality sentence (container registry
  is not object storage, and the reverse) and adds ECR to the hint
  list, and bumps `_PROMPT_VERSION` from `"3"` to `"4"`. That is a
  vocabulary sentence, not a new interpreter architecture.
- **Resolver determinism:** additive only — one new `match` arm, no
  clarification arm. `STORAGE` never asks about `interaction_pattern`
  (verified: the existing S3 arm and
  `test_storage_object_storage_resolves_to_s3_spec_regardless_of_interaction_pattern`).
  The one existing "wrong capability under STORAGE" test and golden
  scenario use `{PERSISTENCE}`, not this new member (§1.3).
- **Existing golden datasets:** every scenario in
  `evals/datasets/architecture_intent_resolver_golden.json` was
  re-read. None names `container_registry`. None is a `STORAGE`
  workload whose capability set becomes newly resolvable.
  `storage_wrong_capability_unsupported_capability` stays
  `{persistence}` → `UNSUPPORTED_CAPABILITY`.
  `schema_invalid_unknown_capability` stays `background_processing` →
  schema-invalid. `evals/datasets/architecture_intent_nl_golden.json`
  likewise has no container-registry expectation. No existing
  scenario's expected outcome changes. New scenarios are additive
  (§13). This is the opposite of Batch 26, which had to rewrite an
  existing "case 7" expectation. The CI command must still be run:
  other existing assertions outside those datasets do change (§14).
- **Backward compatibility:** the `Capability` enum is `frozenset`-typed
  on `ArchitectureIntent` and matched by *exact set equality*
  everywhere in the resolver (never subset/superset) — adding a member
  cannot change the outcome of any existing intent that doesn't
  reference it.

**Also closed (lower-stakes, purely additive):** one new
`AwsServiceHint.ECR = "ecr"` member — non-authoritative, never read by
the resolver, matching the existing precedent that every `ResourceType`
member also has a same-named `AwsServiceHint` twin.

`Capability`'s docstring currently says "Exactly these four members".
That sentence is updated in the same change that adds
`CONTAINER_REGISTRY`. `BACKGROUND_PROCESSING` stays rejected.

## 5. Terraform module strategy

No trusted ECR module exists (§1.12). Design the smallest reasonable
one: exactly one managed resource, `aws_ecr_repository`, with its two
native nested blocks (`image_scanning_configuration`,
`encryption_configuration`) populated directly from the contract —
**no sidecar resources**, unlike S3's four-resource module, because
AWS's own schema already inlines these two concerns (§1.13). Outputs:
`arn`, `repository_url`, `registry_id` (all real, computed AWS
attributes — no synthesized values).

```
terraform/modules/ecr/
  main.tf       # one aws_ecr_repository
                # image_scanning_configuration { scan_on_push = var.scan_on_push }
                # encryption_configuration { encryption_type = "AES256" }
                #   hardcoded, not a variable — same idea as DynamoDB
                #   hardcoding server_side_encryption.enabled = true
                # no force_delete, no kms_key, no lifecycle, no policy
  variables.tf  # name, image_tag_mutability, scan_on_push, tags
  outputs.tf    # arn, repository_url, registry_id
  versions.tf   # required_version >= 1.5.0, aws ~> 6.0
```

Not implemented this batch (design only).

## 6. Renderer strategy

One new `EcrTerraformCompositionRenderer` (the standalone-resource
class name used by S3, DynamoDB, Lambda, and API Gateway — not the
shorter composition-renderer suffix). It mirrors
`providers/aws/s3/renderer.py`: pure string-templating functions using
the shared `iac_agent.providers.aws.terraform_render` primitives, a
single `module "ecr" { source = ...; ... }` block, `versions.tf` reused
verbatim via `render_versions_tf()`. No relationship resources to
render (no IAM policy, no event source mapping). Wiring it requires a
new constructor parameter and a new `case` on `AWSResourceRenderer`
in `providers/aws/renderer.py`. `request.py`'s `IacRenderer` does not
change: its `case _` already forwards any `AWSResourceSpec` through
`resource_type_of()` to `AWSResourceRenderer`.

## 7. Security defaults and policy IDs — CLOSED

Exact names confirmed against the real current naming convention in
`policies/platform.py` (module-level string constants, `<ABBREV>_
<PROPERTY>_REQUIRED`/`_RECOMMENDED` — e.g. `S3_ENCRYPTION_REQUIRED`,
`DDB_PITR_RECOMMENDED`, checked directly against the file on `main`):

- **`ECR_ENCRYPTION_REQUIRED`** — hard invariant. A constructible
  `EcrResourceSpec` always has `encryption.enabled=True`, so the
  reachable result is PASS. The evaluator still contains the same
  defense-in-depth BLOCK branch SQS/S3/DynamoDB use if a False value
  ever reached this layer. Rendered as `encryption_configuration {
  encryption_type = "AES256" }` — the AWS-managed-key default, per the
  closed §2 decision. AES256 is the supported contract, not a WARN.
- **`ECR_SCAN_ON_PUSH_RECOMMENDED`** — caller-toggleable
  `scan_on_push`, default `True`, WARN if disabled (mirrors
  `DDB_PITR_RECOMMENDED`/`S3_VERSIONING_RECOMMENDED` exactly).
- **`ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED`** — caller-toggleable
  `image_tag_mutability`, default `IMMUTABLE`, WARN if `MUTABLE`.
  Immutability is a genuine security property here (prevents an
  attacker or a mistaken push from silently overwriting a previously-
  scanned, already-deployed image tag), not an arbitrary default
  choice.
- `force_delete` — never exposed on the contract at all; the rendered
  module never sets it, so it takes AWS's own safe default (`false`) —
  a repository containing images can never be silently force-deleted
  through this platform. No field, no policy needed — mirrors how
  `terraform apply`/`destroy` are absent by omission everywhere else
  in this codebase.

No generalized policy taxonomy/refactor is introduced — these three
IDs slot directly into the existing `REQUIRED_PLATFORM_POLICY_IDS_
BY_RESOURCE_TYPE` / `evaluate_platform_policies()` shape (§20).

## 8. IAM implications

**None.** An `aws_ecr_repository` on its own creates no IAM role, no
resource-based policy, no cross-service permission of any kind (unlike
`aws_ecr_repository_policy`, deliberately out of scope — see §19). No
`aws_iam_role_policy`, no interaction with `TerraformRunner` (which
still has no `apply`/`destroy` method, unaffected either way), and
critically: **no interaction whatsoever with Batch 25's
`bootstrap/aws-oidc`/`IaCPlanRole` boundary** — confirmed no file under
`bootstrap/` or `ci/aws_plan/` needs to exist, be read, or be modified
for this design.

## 9. Checkov empirical methodology (never predicted)

Identical 8-step procedure to Batch 26's Task 16, restated here as the
committed methodology, not pre-empted with a guessed skip list:

1. Implement the trusted module + renderer (implementation-time).
2. Render a real, secure-default `EcrResourceSpec` composition.
3. Run the existing strict, zero-skip real-tool Checkov path against it.
4. Capture every real finding verbatim.
5. Classify each individually: genuine defect / accepted architectural
   trade-off (with a specific, non-generic justification) / false
   positive.
6. Fix any genuine defect in the renderer/module, re-scan.
7. Freeze only the empirically justified skip list into
   `security/checkov_profiles.py`, with a regression test asserting the
   frozen list exactly.
8. Prove the final scan (frozen skips applied) passes cleanly.

**Plausible (not assumed) candidate findings, for context only, never
to be adopted without step 3 actually running:** an encryption-related
check parallel to DynamoDB's own `CKV_AWS_119`-style customer-KMS
deferral is plausible given the `encryption.enabled`-but-AES256-only
design in §7 — but this is explicitly a guess to be replaced by real
Gate-B evidence, not a design-time decision.

## 10. Persistence/durability implications

**Yes — a new, concrete registration requirement, exactly the pattern
Batch 26's Task 7 found.** `EcrResourceSpec` (plus its two nested
enum/model types, `EcrImageTagMutability` and `EcrEncryptionSpec`) must
each get their own `(module, qualname)` entry in `persistence.
checkpoints._ALLOWED_WORKFLOW_TYPES` — three new tuples, mirroring
exactly how `LambdaRuntime`/`LambdaArchitecture`/`LambdaTracingMode`
each got their own entry alongside `LambdaResourceSpec` itself.

**Explicit type-preservation test design** (implementation-time, Gate
B, mirrors Batch 26's Task 18 exactly):

```python
def test_ecr_spec_survives_fresh_process_checkpoint_reconstruction():
    # real graph -> real HITL interrupt -> close -> fresh
    # checkpointer + fresh compiled graph, same DB file -> get_state
    assert type(recovered["resource_spec"]) is EcrResourceSpec
    assert not isinstance(recovered["resource_spec"], dict)
    # resume with APPROVE through to source_control (fake adapter)
```

Plus the narrower, Gate-A-safe isolated `JsonPlusSerializer` round-trip
proof (mirrors Batch 26's Task 7, catches the exact "silently degrades
to dict" failure mode without needing real Terraform/Checkov at all).

## 11. Workflow implications

**None to `graph/workflow.py`'s node logic.** Confirmed by §1.7: every
node already dispatches standalone resources via `dict[ResourceType,
X]` lookups (`_DEFAULT_TRUSTED_MODULE_DIRS`, `_RESOURCE_KIND_DISPLAY_
NAMES`) or through the generic `AWSResourceRenderer`/
`evaluate_platform_policies`/`checkov_profile_for` dispatch already
proven to handle any registered `ResourceType`. Adding ECR means
**two new dict entries**, not a new `match`/`case` arm anywhere in this
file — a real, structural difference from composition work, and
concrete evidence for §17.

## 12. CLI/presentation implications — CLOSED (generalized fail-closed design)

Confirmed live, pre-existing bug (§1.10): without a fix,
`_architecture_label(EcrResourceSpec(...))` would silently return
`"s3"`. **Decision: fix generally, not just for ECR** — per decision
#6, do not add `if ECR -> "ecr"` and leave the unconditional fallback
in place for the next resource type.

**Design: replace the `isinstance`-chain-with-silent-fallback for
standalone resources with a `dict[ResourceType, str]` lookup through
`resource_type_of()`** — this is not a new abstraction; it is the
*same* pattern `graph/workflow.py`'s own `_RESOURCE_KIND_DISPLAY_NAMES`
already uses for commit-message text (§1.7/§17), applied consistently
to the one place that had instead used `isinstance` + a silent
default. A `dict` lookup fails **loudly** (`KeyError`) for an
unregistered key; an `isinstance` chain with a bare `return "s3"`
fails **silently**. This is the fix, not a coincidence of also adding
ECR:

```python
_STANDALONE_RESOURCE_LABELS: dict[ResourceType, str] = {
    ResourceType.SQS: "sqs",
    ResourceType.S3: "s3",
    ResourceType.DYNAMODB: "dynamodb",
    ResourceType.LAMBDA: "lambda",
    ResourceType.API_GATEWAY: "api_gateway",
    ResourceType.ECR: "ecr",
}

def _architecture_label(spec: IacRequestSpec) -> str:
    if isinstance(spec, ServerlessWorkerSpec):
        return "serverless_worker"
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        return _API_LAMBDA_DYNAMODB_ARCHITECTURE_LABEL
    if isinstance(spec, ApiLambdaSpec):
        return "api_lambda"
    return _STANDALONE_RESOURCE_LABELS[resource_type_of(spec)]
```

Deliberately **not** centralized with `graph/workflow.py`'s own
`_RESOURCE_KIND_DISPLAY_NAMES` — that dict serves a different
presentation context (capitalized PR/commit text, e.g. `"API Gateway"`)
with different value conventions than this one (lowercase CLI labels,
e.g. `"api_gateway"`). Two small, independently-registered dicts, same
idiom, no shared cross-cutting registry — consistent with §20's
closed decision not to introduce a registry for this fix.

**Exhaustiveness regression test** (mirrors
`test_every_resource_type_has_a_non_empty_display_name` in
`test_resource_registration_consistency.py` exactly):

```python
def test_every_resource_type_has_a_cli_architecture_label():
    for resource_type in ResourceType:
        assert resource_type in _STANDALONE_RESOURCE_LABELS
```

This makes "add a future `ResourceType` without registering its CLI
label" fail a deterministic test at commit time, **and** fail loudly
(`KeyError`) at runtime even if the test were somehow skipped —
closing the general version of this sharp edge, not just the
ECR-specific instance, so a sixth resource type doesn't reopen it a
third time.

## 13. Golden-eval strategy

Minimal dataset, nine scenarios, no padding:

- `basic_secure_repository` — name only; defaults `IMMUTABLE`,
  `scan_on_push=True`, encryption enabled; overall security PASS.
- `namespaced_repository_name` — `team/service` is valid.
- `scan_on_push_disabled_warns` — valid, `ECR_SCAN_ON_PUSH_RECOMMENDED`
  is WARN.
- `mutable_tags_warn` — valid, `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED`
  is WARN.
- `uppercase_name_rejected`
- `empty_name_rejected`
- `leading_slash_rejected`
- `name_too_long_rejected` — 257 characters.
- `invalid_character_rejected` — a character outside the regex
  (a space).

Byte-identical render-twice determinism is a renderer unit test, not
a tenth golden scenario.

**Resolver golden dataset — additive only.** Two new scenarios in
`evals/datasets/architecture_intent_resolver_golden.json`, and the same
two IDs added to `_REQUIRED_SCENARIO_IDS` in
`tests/integration/test_architecture_intent_golden_evals.py`:

- `storage_container_registry_resolves_to_ecr_repository` —
  `STORAGE` + `{CONTAINER_REGISTRY}` + `interaction_pattern=unspecified`
  resolves to `EcrResourceSpec`,
  `matched_pattern="storage+container_registry"`. The unit test
  parametrizes `SYNCHRONOUS` / `ASYNCHRONOUS` / `UNSPECIFIED` and
  asserts the same resolution. There is no clarification scenario:
  `STORAGE` has no `interaction_pattern` clarification arm (§4).
- `storage_container_registry_with_object_storage_unsupported_capability`
  — `STORAGE` + `{CONTAINER_REGISTRY, OBJECT_STORAGE}` remains
  `UNSUPPORTED_CAPABILITY`. Exact-set equality must not broaden.

Zero existing scenarios in that file, and zero scenarios in
`architecture_intent_nl_golden.json`, are modified (§4).

## 14. Backward-compatibility strategy

The deterministic CI command, copied from `.github/workflows/ci.yml`'s
`Tests` job, is:

```bash
pytest -m "not real_tool and not real_llm"
```

Quality also runs `ruff check .` and
`terraform fmt -check -recursive -diff terraform/ tests/terraform/`.
Gate A is not closed until all three have been run. `tests/unit` alone
is the Batch 26 miss: a non-real-tool integration golden dataset is
inside the marker expression and outside `tests/unit`.

**Existing golden expectations that do not change.** Every scenario in
`evals/datasets/architecture_intent_resolver_golden.json` and
`evals/datasets/architecture_intent_nl_golden.json` was read. None
expects `container_registry`. Promoting `STORAGE + {CONTAINER_REGISTRY}`
from unrepresentable to resolved does not rewrite any existing
scenario. The resource golden datasets (`s3`, `sqs`, `dynamodb`,
`lambda`, and the three composition datasets) are untouched.
`_REQUIRED_SCENARIO_IDS` is a subset check, so a new scenario is
executed with the rest of the file even before its ID is listed; the
ID is still added in the same change so the required set stays
explicit. Batch 26's failure mode was an *existing* scenario whose
expected outcome went stale. That specific collision is absent here.
The full command is still mandatory, because other existing assertions
will fail until they are updated:

- `tests/unit/domain/test_resource.py` asserts `ResourceType` is
  exactly `{sqs, s3, dynamodb, lambda, api_gateway}`.
- `tests/unit/test_resource_registration_consistency.py` asserts
  `set(_EXAMPLE_SPECS) == set(ResourceType)` and that every member has
  a policy-ID tuple, a Checkov profile, an on-disk trusted module
  directory, a display name, a `resource_type_of` result, and a
  renderer case. Adding `ResourceType.ECR` before those registrations
  fails this file.
- `tests/unit/intent/adapters/test_openai_prompt_contract.py` asserts
  `_PROMPT_VERSION == "3"`.

Existing composition and standalone-resource behavior stays green.
Assertions in those suites are extended only where a file above
already enumerates the closed set. No Batch 25 or Batch 26 production
file is edited for ECR behavior.

## 15. Exact dispatch/registration inventory (production)

Recounted at closure against the current code. The interrupted draft's
"19" omitted `AWSResourceRenderer`, which is a real `match` site in
`providers/aws/renderer.py`. The interpreter prompt is listed after
the dispatch table because it is required production code and it is
not a dispatch site.

| # | File | Function/Class/Constant | Reason | Coupling type |
|---|---|---|---|---|
| 1 | `domain/resource.py` | `ResourceType` | new `ECR = "ecr"` member | domain enumeration |
| 2 | `providers/aws/ecr/contract.py` (new) | `EcrResourceSpec`, `EcrImageTagMutability`, `EcrEncryptionSpec` | new contract | domain enumeration |
| 3 | `providers/aws/ecr/renderer.py` (new) | `EcrTerraformCompositionRenderer` | new renderer | rendering |
| 4 | `providers/aws/resource.py` | `AWSResourceSpec` union | widen union | domain enumeration |
| 5 | `providers/aws/resource.py` | `resource_type_of()` | new `case` arm | resolver-adjacent dispatch |
| 6 | `providers/aws/renderer.py` | `AWSResourceRenderer` | new constructor parameter and `case` arm | rendering |
| 7 | `policies/platform.py` | `ECR_ENCRYPTION_REQUIRED`, `ECR_SCAN_ON_PUSH_RECOMMENDED`, `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED` | ECR-specific findings | policy |
| 8 | `policies/platform.py` | `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` | new entry, including `TF_NO_DESTRUCTIVE_CHANGES` | policy |
| 9 | `policies/platform.py` | `evaluate_platform_policies()` | new `case` arm | policy |
| 10 | `security/checkov_profiles.py` | `_PROFILES_BY_RESOURCE_TYPE` | Gate A registers `skipped_checks=()`; Gate B may replace only that tuple | security profile |
| 11 | `graph/workflow.py` | `_DEFAULT_TRUSTED_MODULE_DIRS` | new entry | rendering |
| 12 | `graph/workflow.py` | `_RESOURCE_KIND_DISPLAY_NAMES` | new entry, value `"ECR"` | workflow (PR/commit text) |
| 13 | `persistence/checkpoints.py` | `_ALLOWED_WORKFLOW_TYPES` | 3 tuples: `EcrResourceSpec`, `EcrImageTagMutability` (enum), `EcrEncryptionSpec` (model) | serialization |
| 14 | `cli/present.py` | `_STANDALONE_RESOURCE_LABELS` / `_architecture_label()` | fail-loud dict (§12) | CLI/presentation |
| 15 | `cli/present.py` | `_component_lines()` | new `isinstance` branch for name, mutability, and scan | CLI/presentation |
| 16 | `intent/models.py` | `Capability` | new member; docstring currently says "exactly these four members" | domain enumeration |
| 17 | `intent/models.py` | `AwsServiceHint` | new `ECR = "ecr"` member | domain enumeration |
| 18 | `intent/resolver.py` | `ArchitectureResolver.resolve()` | one new `case` arm; no clarification arm | resolver |
| 19 | `intent/resolver.py` | `_build_ecr_spec()` | new builder | resolver |
| 20 | `terraform/modules/ecr/*.tf` (new) | one `aws_ecr_repository` | new trusted module | rendering |

**20 dispatch/registration sites, all required.** `request.py` is
absent on purpose: `IacRenderer.render()`'s `case _` already forwards
a standalone spec. `graph/workflow.py`'s composition `match` arms are
absent on purpose: a standalone spec already falls through to
`resource_type_of()` (§1.7, re-read at closure).

**One additional production site, not a dispatch site:**

| # | File | Change |
|---|---|---|
| 21 | `intent/adapters/openai.py` | Add a capability-orthogonality sentence distinguishing `container_registry` from `object_storage`, mention ECR in the hint list, bump `_PROMPT_VERSION` from `"3"` to `"4"`. The JSON schema needs no separate edit. |

Documentation written in the same batch, not counted as dispatch
sites: `docs/resources/ecr.md` (new), a Batch 27 section in
`docs/roadmap.md`, and the supported-resource sentences in `README.md`.

This table is the **theoretical** inventory. The implementation plan
and the Batch 27 closure report record the **actual** sites touched,
separately, so the two can be compared (§20).

## 16. Exact test/eval inventory

| # | File | Reason |
|---|---|---|
| 1 | `tests/unit/providers/aws/ecr/test_ecr_contract.py` (new) | contract validation, including the encryption validator and the ECR name regex |
| 2 | `tests/unit/providers/aws/ecr/test_ecr_renderer.py` (new) | renderer output, including byte-identical double render |
| 3 | `tests/unit/policies/test_ecr_platform_policies.py` (new) | PASS / WARN / defense-in-depth BLOCK |
| 4 | `tests/unit/graph/test_workflow_ecr.py` (new) | display name `"ECR"`, trusted module dir, standalone policy path |
| 5 | `tests/unit/evals/test_ecr_loader.py` (new) | loader rejects a malformed dataset |
| 6 | `evals/datasets/ecr_golden.json` (new) | nine scenarios (§13) |
| 7 | `evals/scenarios/ecr_loader.py` (new) | loader |
| 8 | `evals/scenarios/ecr_runner.py` (new) | runner |
| 9 | `evals/evaluators/ecr.py` (new) | evaluator |
| 10 | `tests/integration/test_ecr_golden_evals.py` (new, Gate A) | deterministic golden suite, not `real_tool` |
| 11 | `tests/integration/test_ecr_renderer_terraform.py` (new, Gate B) | real Terraform proof |
| 12 | `tests/integration/test_ecr_golden_real_tool_eval.py` (new, Gate B) | real Terraform + Checkov proof |
| 13 | `tests/integration/test_ecr_workflow_persistence.py` (new, Gate B) | fresh-process durable HITL proof |
| 14 | `tests/unit/domain/test_resource.py` | exact member set gains `"ecr"` |
| 15 | `tests/unit/providers/aws/test_resource_dispatch.py` | `resource_type_of` |
| 16 | `tests/unit/providers/aws/test_renderer_dispatch.py` | `AWSResourceRenderer` |
| 17 | `tests/unit/security/test_checkov_profiles.py` | profile lookup does not raise; Gate B freezes the skip tuple |
| 18 | `tests/unit/test_resource_registration_consistency.py` | one example `EcrResourceSpec` |
| 19 | `tests/unit/persistence/test_checkpoints_allowed_types.py` | isolated serializer round-trip (`type(...) is EcrResourceSpec`) |
| 20 | `tests/unit/cli/test_present.py` | label exhaustiveness, and ECR is not `"s3"` |
| 21 | `tests/unit/intent/test_architecture_resolver.py` | new arm, all three interaction patterns, fail-closed mixed set |
| 22 | `evals/datasets/architecture_intent_resolver_golden.json` | two additive scenarios; zero existing scenarios edited |
| 23 | `tests/integration/test_architecture_intent_golden_evals.py` | the same two IDs added to `_REQUIRED_SCENARIO_IDS` |
| 24 | `tests/unit/intent/adapters/test_openai_prompt_contract.py` | version `"4"`, and the prompt names `container_registry` as distinct from `object_storage` |

**24 test/eval sites.** The interrupted draft's "20" folded four eval
files into one row, pointed persistence at a file that does not exist
(`test_checkpoints.py`; the file on disk is
`test_checkpoints_allowed_types.py`), and omitted the domain member-set
test, the loader unit test, and the prompt-contract test.

### Silent-failure risk classification

| Site | Omission fails... |
|---|---|
| `ResourceType` / `AWSResourceSpec` / `resource_type_of` / `AWSResourceRenderer` | **loudly** — `ValueError` at first dispatch |
| `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` / `evaluate_platform_policies` | **loudly** — `KeyError` or fail-closed `raise` |
| `checkov_profile_for` | **loudly** — `ValueError` |
| `_DEFAULT_TRUSTED_MODULE_DIRS` | **loudly** — `KeyError` at render time |
| `_RESOURCE_KIND_DISPLAY_NAMES` | **loudly** — `KeyError` at commit-message time |
| **`_ALLOWED_WORKFLOW_TYPES`** | **silently** — Batch 26 Task 7: unregistered type degrades to a raw `dict`, no exception. Not covered by `test_resource_registration_consistency.py`. Detected only by an explicit `type(...) is` assertion |
| **`_architecture_label` today** | **silently** — live `return "s3"` (§1.10). The §12 dict turns a missing standalone label into `KeyError`. The exhaustiveness test fails at commit time |
| **`_component_lines`** | **silently** — still `return []` for a standalone spec with no branch. ECR gets a branch. A later resource type without one still prints no detail lines. Not converted to a dict in this batch |
| `Capability` without a resolver row | **loudly** — `UnsupportedArchitecture` / `UNSUPPORTED_CAPABILITY` for an unmapped `STORAGE` set. Never silently mis-resolves |
| **`_INSTRUCTIONS` without a `container_registry` sentence** | **silently** — the schema already allows the new enum value, and existing prompt tests still pass, while the prose can steer a registry request to `object_storage` and therefore to S3. The new prompt-contract assertion is what makes this omission loud |

Two silent classes are structural and already seen once each in Batch
26: the checkpoint allowlist, and CLI presentation. The label half of
the CLI class is closed in this batch. The component-line half stays
an empty list, by the decision not to build a registry for it. The
prompt-prose class is new to this batch because this is the first
`Capability` addition since the interpreter prompt was written.

## 17. Scalability/friction analysis

Comparing this ECR inventory with Batch 26's composition inventory:

- **Volume.** 20 dispatch/registration sites, plus one interpreter-
  prompt site. Batch 26's composition work was smaller by site count.
  ECR is not cheaper to register than a composition just because it is
  one resource. The extra sites are the contract, the trusted module,
  the platform policies, and the prompt sentence. They are not IAM
  resources (§8).
- **Character.** Batch 26 widened existing grouped `match` arms in
  `graph/workflow.py`. ECR adds two dict entries there and no new
  `match` arm in that file. `match`/`case` remains on
  `resource_type_of`, `AWSResourceRenderer`, and
  `evaluate_platform_policies`, where the concrete type is what the
  code has to narrow. The four `dict[ResourceType, X]` maps are
  already table-shaped.
- **Silent omissions** are the repeated cost (§16), not the loud
  `KeyError` / `ValueError` sites.

**This count is theoretical.** The implementation plan and the Batch
27 closure report record, separately:

- actual production sites modified,
- actual test/eval sites modified,
- which changes were mechanical registration versus new behavior
  (contract, renderer, label dict, prompt sentence),
- which omissions failed loudly versus silently, checked against what
  the tests actually caught.

Only after that comparison should Batch 28 reopen the registry
question. Moving maps into another abstraction is not, by itself,
enough reason (§20, §21).

## 18. Implementation gates proposal (design intent only — not the plan)

Mirrors Batch 26's own Gate A / Gate B split exactly, since the same
credential-free real-tool discipline applies identically:

- **Gate A (deterministic/offline):** contract, renderer unit
  assertions, the 20 dispatch sites, the prompt sentence, golden
  datasets (§13), and docs. Checkov is registered in Gate A as
  `CheckovScanProfile(skipped_checks=())` because
  `test_every_resource_type_has_a_checkov_profile` fails closed as
  soon as `ResourceType.ECR` exists. That empty tuple is not a
  predicted skip list. Gate A closes only when all three CI quality
  commands have been run (§14): `pytest -m "not real_tool and not
  real_llm"`, `ruff check .`, and `terraform fmt -check -recursive
  -diff terraform/ tests/terraform/`.
- **Gate B (real Terraform + real Checkov, still credential-free):**
  `fmt` / `init` / `validate` / `plan` / `show` on rendered ECR,
  a first Checkov scan with the Gate A zero-skip profile, finding-by-
  finding classification (§9), a frozen profile only where a finding
  is an accepted trade-off, real-tool golden eval, and a fresh-process
  durable HITL reconstruction. Also the Gate B check of whether the
  provider accepts a leading digit in a repository name (§2).
- No Gate C/D/E. Nothing here uses real AWS credentials, GitHub
  writes, or an OpenAI call. `real_llm` stays excluded.

## 19. Explicit non-goals

- `aws_ecr_repository_policy` (cross-account/service pull permissions)
  — a genuine IAM-adjacent extension, deliberately deferred; would be
  this batch's first real IAM-implications item if added, and isn't
  needed for "push/pull your own images" minimal scope.
- `aws_ecr_lifecycle_policy` — **explicitly evaluated per the stated
  preference: not included this batch.** No strong architectural/
  security reason was found requiring it for a minimal vertical slice
  (unlike encryption/scan-on-push/immutability, which are direct,
  well-established AWS security best practices this project already
  applies analogous WARN-policies for elsewhere). If a future batch
  adds it, it should be an explicit, typed sub-contract (e.g.
  `EcrLifecyclePolicySpec` with concrete, closed rule fields), never
  a raw JSON passthrough or hidden default behavior — consistent with
  this project's "no generic policy DSL" invariant already stated for
  `api_lambda`'s own IAM design.
- `aws_ecrpublic_repository` (public ECR) — out of scope, private ECR
  only.
- `image_tag_mutability_exclusion_filter` — needs the exclusion-filter
  nested block, adds real complexity, no demonstrated need.
- Customer-managed KMS for ECR encryption — deferred (§2, §7),
  mirrors DynamoDB's own precedent.
- Registry-level ECR scanning configuration
  (`aws_ecr_registry_scanning_configuration`) — noted in §2 as AWS's
  own documented future direction for the per-repository
  `scan_on_push` field; not part of this vertical slice.
- A Composition/Resource Registry refactor — explicitly this batch's
  measurement subject, not its deliverable (§17/§21).
- Any change to Batch 25's OIDC/bootstrap boundary or Batch 26's three
  compositions — confirmed untouched throughout this design.
- Agent Observability/LLMOps (e.g. Langfuse) — recorded as a future
  platform-level pressure test (§22), not this batch's scope, and
  conceptually never a Checkov/policy-enforcement mechanism regardless
  of when it is eventually introduced.

## 20. Design decisions — CLOSED this round

1. **`Capability.CONTAINER_REGISTRY` (§4).** `WorkloadType.STORAGE` is
   reused. `OBJECT_STORAGE` is not reinterpreted. Exact tuple:
   `STORAGE` + any `interaction_pattern` +
   `frozenset({Capability.CONTAINER_REGISTRY})` → `EcrResourceSpec`,
   `matched_pattern="storage+container_registry"`. No clarification
   arm. Any other `STORAGE` capability set stays
   `UNSUPPORTED_CAPABILITY`.
2. **`EcrEncryptionSpec` (§2, §7).** `enabled=True` enforced by a
   field validator, not by the default alone. No `kms_key_id`. AES256
   only. The module hardcodes `encryption_type = "AES256"`.
3. **Policy IDs (§7).** `ECR_ENCRYPTION_REQUIRED` (PASS for every
   constructible spec, BLOCK only in the unreachable defense-in-depth
   branch). `ECR_SCAN_ON_PUSH_RECOMMENDED` and
   `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED` (WARN).
4. **`_architecture_label` (§12).** A `dict[ResourceType, str]` plus
   an exhaustiveness test. Not an ECR-only branch above `return "s3"`.
   `_component_lines` gets an ECR branch and stays an `isinstance`
   chain. No registry is introduced to fix the label bug.
5. **No registry refactor (§17, §21).** Preserve explicit dispatch.
   Compare the theoretical inventory (§15, §16) with the actual sites
   touched after implementation. Possibly justified later, premature
   now.
6. **Interpreter prompt (§4).** Schema widens with the enums. Prose
   gets one orthogonality sentence and an ECR hint, and
   `_PROMPT_VERSION` becomes `"4"`.
7. **Checkov skips are not designed here (§9, §18).** Gate A registers
   an explicit empty skip tuple. Gate B freezes only empirical
   findings.
8. **Lifecycle policy is out of scope (§19).** No implicit lifecycle
   resource and no raw JSON policy field.

No unresolved design decisions remain. One implementation-time
verification is not a design fork: AWS prose says a repository name
"must start with a letter" while the published regex allows a leading
digit. The Pydantic validator follows the regex. Gate B records what
`terraform validate` / `plan` actually accept.

## 21. Batch 28 registry decision — evidence-based answer

**Possibly justified but premature, and only for a narrow slice of the
current architecture — not the `match`/`case` dispatch layer.**

Evidence for a *narrow* registry (the four `dict[ResourceType, X]`
maps — trusted module dirs, display names, required policy IDs,
Checkov profiles — consolidated into one `ResourceDefinition`
dataclass registered once per type):

- These four maps are already structurally identical
  (`ResourceType`-keyed, one entry per type, no branching logic) —
  consolidating them would reduce "4 dict edits" to "1 registration",
  and would **directly eliminate** one of the two confirmed
  recurring silent-failure classes only if the registration itself
  is exhaustiveness-checked against `ResourceType` at import/test time
  (which `test_resource_registration_consistency.py` already does
  today, manually, via `set(_EXAMPLE_SPECS) == set(ResourceType)`).
- This would not, by itself, fix the *other* confirmed recurring
  silent-failure class (`_ALLOWED_WORKFLOW_TYPES`,
  `cli/present.py`'s `isinstance` chains) — those aren't
  `ResourceType`-keyed maps, they're keyed by concrete Python type,
  which is a different registration shape a "resource metadata"
  registry wouldn't naturally cover without also becoming a type-
  dispatch registry (see below).

Evidence against a *broad* registry replacing `match`/`case` dispatch
(`resource_type_of`, `evaluate_platform_policies`, `AWSResourceRenderer`,
`ArchitectureResolver`, `_architecture_label`):

- Python's structural pattern matching on concrete types already gives
  fail-closed behavior (`case _: raise`) and is directly readable —
  a `dict[type, Callable]` table-driven replacement would need its own
  explicit "every registered type has an entry" test to recover the
  same guarantee, which is exactly what `test_resource_registration_
  consistency.py`/`test_composition_registration_consistency.py`
  already provide today, external to the dispatch code itself.
- A registry does not automatically prevent the *specific* silent-
  failure classes actually observed twice in this codebase — both
  were caused by a **missing entry**, not by the *shape* of the
  existing table/match dispatch. A registry that itself has an
  omittable-without-error registration step would reproduce the exact
  same risk under a different name. The evidence argues for **better
  registration-completeness tests** (which this project's own two
  `test_*_registration_consistency.py` files already are) more
  directly than for a new abstraction layer.

**Conclusion:** the site count and the repeated maps are real. They
do not yet show that a registry would remove the silent classes
instead of relocating them. The checkpoint allowlist and the CLI
presentation bug are the two classes already seen in Batch 26. This
batch closes the label half of the CLI class with a dict and a test,
and leaves `_component_lines` as an `isinstance` chain. The
interpreter-prompt sentence (§16) is a third silent class, and a
resource-metadata registry would not cover it, because it is prose
rather than a `ResourceType`-keyed map. Implementing ECR as designed,
then comparing theoretical sites with actual sites, is the evidence
Batch 28 should use. A registry is not ruled out. It is not this
batch's deliverable.

Not implemented this batch.

## 22. Future roadmap — documentation only

Batch 27 designs ECR only. The following are pressure tests for later
batches, not scope:

- Customer-managed KMS, including the ECR `kms_key` path deferred in
  §2.
- CloudFront + S3 + origin access control.
- SNS / EventBridge.
- Secrets Manager.
- ECS/Fargate together with this ECR repository.
- ALB / networking.
- RDS / Aurora.
- Registry-level ECR scanning
  (`aws_ecr_registry_scanning_configuration`), the direction AWS
  documents for the per-repository `scan_on_push` field (§2).

**Agent Observability / LLMOps**, potentially using Langfuse, is a
future platform capability. It is not an AWS resource, not a Checkov
profile, not a deterministic platform policy, and not AWS
infrastructure monitoring. It must not be wired into
`evaluate_platform_policies`, `checkov_profile_for`, or the security
gate. It is not implemented in Batch 27.

---

No production implementation is part of this document. The
implementation plan is a separate file, written after this closure.
No `terraform apply` / `destroy`. No AWS call. No OpenAI call. No
GitHub mutation. Batch 25's `bootstrap/aws-oidc` / `ci/aws_plan` and
Batch 26's three compositions are not modified by this design.

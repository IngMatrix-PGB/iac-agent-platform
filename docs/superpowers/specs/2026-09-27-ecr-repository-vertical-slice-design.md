# Batch 27 — ECR Repository vertical slice (design)

Discovery base: `origin/main` `037edf6` (PR #9, Batch 26's third
composition, merged 2026-09-27). Verified directly (`git fetch` +
`git diff origin/main HEAD` empty) before any discovery began, not
assumed. Design-only: no implementation, no `terraform apply`/
`destroy`, no AWS credentials, no AWS/OpenAI call, no GitHub mutation.
Batch 25's deferred AWS-plan-boundary Tasks 12–16 and Batch 26 are
untouched throughout.

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
`storage+object_storage → S3ResourceSpec`), two clarification rows,
and a fail-closed `case _` classifying everything else as
`UnsupportedArchitecture` (`UNSUPPORTED_CAPABILITY` specifically for
any unmapped `STORAGE`-workload combination, `UNSUPPORTED_COMBINATION`
otherwise — see `_classify_unsupported`).

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
hard invariant (always PASS, because the contract makes the insecure
state unrepresentable — e.g. `S3_ENCRYPTION_REQUIRED`,
`DDB_ENCRYPTION_REQUIRED`), `<RESOURCE>_<PROPERTY>_RECOMMENDED` for a
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

## 2. Proposed ECR domain model

```python
class EcrImageTagMutability(StrEnum):
    MUTABLE = "MUTABLE"
    IMMUTABLE = "IMMUTABLE"
    # MUTABLE_WITH_EXCLUSION / IMMUTABLE_WITH_EXCLUSION deliberately
    # excluded — see §12 non-goals (needs the exclusion-filter block).

class EcrEncryptionSpec(BaseModel):
    """Mirrors SQS's EncryptionSpec / S3's S3EncryptionSpec / DynamoDB's
    DynamoDBEncryptionSpec exactly: enabled=True is a hard invariant,
    unrepresentable as False, by construction."""
    enabled: bool = True
    # No kms_key_id — mirrors DynamoDBEncryptionSpec's own minimalism
    # (customer-managed KMS evaluated and deferred, not this batch's
    # scope), not S3EncryptionSpec's (which does carry one). This is
    # an open decision — see §20.

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

**Naming validator — cannot reuse an existing pattern verbatim.** Real
AWS ECR repository name rules (verified against current AWS
documentation) differ from every existing contract's name regex in
this project: lowercase letters, digits, hyphens, underscores,
periods, and forward slashes (`/`, for namespacing e.g. `team/service`),
2–256 characters, must start with a letter or number. This is neither
a superset nor a subset of the existing `^[a-zA-Z0-9_-]+$` pattern used
by SQS/S3/DynamoDB/Lambda/API-Gateway (those forbid `.`/`/`; ECR
forbids uppercase, which the others allow). A new, ECR-specific
validator is required — not a shared regex, and not a copy-paste of an
existing one. `resolve_base_name`/`component_name`'s own output
(lowercase-hyphenated) already satisfies ECR's rules with no changes
needed there.

`scan_on_push` and `image_tag_mutability` are ordinary, caller-toggleable
fields with safe defaults (mirroring `DynamoDBResourceSpec.
point_in_time_recovery`/`deletion_protection` exactly) — disabling
either is a legitimate, WARN-flagged choice, not construction-time
rejected. `encryption.enabled` is a hard invariant (mirroring SQS/S3/
DynamoDB's own `EncryptionSpec` pattern) — there is no way to construct
an `EcrResourceSpec` representing an unencrypted repository at all.

## 3. Standalone-resource vs. composition decision

**Recommendation: Option A — a standalone resource
(`ResourceType.ECR`), not a composition, not an extension of an
existing abstraction.**

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

## 4. `ArchitectureIntent` mapping analysis

**Finding: the current vocabulary genuinely cannot represent "I need a
container image registry" without reinterpreting an existing member.**
This is surfaced explicitly, per instruction, rather than silently
worked around.

- `WorkloadType.STORAGE` fits without change — a container registry
  is a storage-shaped workload exactly like S3, and mirrors the
  existing precedent that `STORAGE` resolves regardless of
  `interaction_pattern` (`test_storage_object_storage_resolves_to_s3_spec_
  regardless_of_interaction_pattern`).
- No existing `Capability` member honestly represents it.
  `OBJECT_STORAGE` is the closest but semantically distinct (see §3).
  `PERSISTENCE`/`HTTP_ENDPOINT`/`QUEUE_PROCESSING` don't apply at all.

**Proposed smallest explicit change:** one new `Capability` member,
e.g. `Capability.CONTAINER_REGISTRY = "container_registry"`, resolved
as `WorkloadType.STORAGE + {Capability.CONTAINER_REGISTRY} →
EcrResourceSpec` — a direct structural sibling of the existing
`WorkloadType.STORAGE + {Capability.OBJECT_STORAGE} → S3ResourceSpec`
row, using `interaction_pattern`-agnostic resolution identically.

**Effects, explicitly:**

- **LLM interpretation:** one new closed-vocabulary word the
  interpreter adapter may emit; Pydantic's existing closed-enum
  validation rejects anything else at parse time exactly as it does
  today — no prompt/schema redesign, only the enum member list grows
  by one (mirrors exactly how Batch 26 added zero new words at all;
  this is the first Batch since 21 to actually widen `Capability`).
- **Resolver determinism:** additive only — one new `match` arm plus
  its `UNSPECIFIED`-interaction-pattern clarification counterpart
  (mirroring the two-arm pattern every existing resolved row uses).
  Verified non-conflicting: the one existing "wrong capability under
  STORAGE" test/golden-scenario uses `{PERSISTENCE}`, not this new
  member (§1.3).
- **Existing golden datasets:** `evals/datasets/
  architecture_intent_resolver_golden.json` needs **no** scenario
  rewritten (unlike Batch 26, which had to correct a real, pre-existing
  "case 7" scenario whose exact capability set Batch 26 newly resolved
  — that was a genuine collision; this new member has no such
  collision, confirmed by inspection of every existing scenario's
  `capabilities` list). It only needs new, additive scenarios for the
  new capability itself (§13).
- **Backward compatibility:** the `Capability` enum is `frozenset`-typed
  on `ArchitectureIntent` and matched by *exact set equality*
  everywhere in the resolver (never subset/superset) — adding a member
  cannot change the outcome of any existing intent that doesn't
  reference it.

**Also proposed (lower-stakes, purely additive):** one new
`AwsServiceHint.ECR = "ecr"` member — non-authoritative, never read by
the resolver, matches the existing precedent that every `ResourceType`
member also has a same-named `AwsServiceHint` twin.

**This is the single largest open decision in this design** — it is
the first `Capability` vocabulary change since Batch 21 explicitly
locked the enum at four members. Flagged for explicit sign-off in §20,
not assumed.

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
  main.tf       # one resource, two nested blocks
  variables.tf  # name, image_tag_mutability, scan_on_push,
                # encryption_type ("AES256" fixed for this batch — see
                # encryption sub-spec decision above), tags
  outputs.tf    # arn, repository_url, registry_id
  versions.tf   # matches every existing module's provider pin
```

Not implemented this batch (design only).

## 6. Renderer strategy

One new `EcrTerraformRenderer` (mirrors `providers/aws/{s3,dynamodb}/
renderer.py`'s exact shape: pure string-templating functions using the
shared `iac_agent.providers.aws.terraform_render` primitives, a single
`module "ecr" { source = ...; ... }` block, `versions.tf` reused
verbatim via `render_versions_tf()`). No relationship resources to
render (no IAM policy, no event source mapping) — the simplest renderer
in the project, simpler than every composition renderer and every
existing standalone-resource renderer except SQS's own minimal case.

## 7. Security defaults

- `encryption.enabled` — hard invariant, `True` unrepresentable as
  `False` (mirrors SQS/S3/DynamoDB exactly). Rendered as
  `encryption_configuration { encryption_type = "AES256" }` — the AWS
  default, matching this project's established precedent (DynamoDB's
  own `DynamoDBEncryptionSpec` also has no customer-KMS field; S3's
  does, but is the outlier, not the rule — two of three existing
  precedents favor the AES256-only minimal shape).
- `scan_on_push` — caller-toggleable, defaults `True`, WARN-if-disabled
  policy (mirrors `DDB_PITR_RECOMMENDED`/`S3_VERSIONING_RECOMMENDED`
  exactly).
- `image_tag_mutability` — caller-toggleable, defaults `IMMUTABLE`,
  WARN-if-`MUTABLE` policy (same pattern). Immutability is a genuine
  security property here (prevents an attacker or a mistaken push from
  silently overwriting a previously-scanned, already-deployed image
  tag), not an arbitrary default choice.
- `force_delete` — never exposed on the contract at all; the rendered
  module never sets it, so it takes AWS's own safe default (`false`) —
  a repository containing images can never be silently force-deleted
  through this platform. No field, no policy needed — mirrors how
  `terraform apply`/`destroy` are absent by omission everywhere else
  in this codebase.

## 8. IAM implications

**None.** An `aws_ecr_repository` on its own creates no IAM role, no
resource-based policy, no cross-service permission of any kind (unlike
`aws_ecr_repository_policy`, deliberately out of scope — see §12). No
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

## 12. CLI/presentation implications

Confirmed live, pre-existing bug (§1.10): without a fix,
`_architecture_label(EcrResourceSpec(...))` would silently return
`"s3"`. This must be fixed as part of this batch's Gate A, mirroring
Batch 26's Task 11 exactly:

```python
def _architecture_label(spec: IacRequestSpec) -> str:
    ...
    if isinstance(spec, EcrResourceSpec):
        return "ecr"
    return "s3"  # still only correct for an actual standalone S3 request
```

**Design for a regression test preventing silent mislabeling**
(mirrors Batch 26's Task 11 test exactly, generalized): a direct unit
test asserting `_architecture_label(EcrResourceSpec(...)) == "ecr"` and
`!= "s3"`, plus (new, broader than Batch 26 attempted) a single
parametrized test asserting `_architecture_label` returns a distinct,
non-`"s3"` label for **every** `ResourceType` member that isn't
actually S3 — closing the *general* version of this sharp edge, not
just the ECR-specific instance of it, so a sixth future resource type
doesn't reopen the same bug a third time.

## 13. Golden-eval strategy

Minimal dataset, mirroring S3's own dataset size/shape (~10-12
scenarios), no padding for count's sake:

- 1–2 valid, secure-default requests (varying name shape: plain name,
  namespaced `team/service`-style name).
- 1 valid request with `scan_on_push=False` → WARN.
- 1 valid request with `image_tag_mutability=MUTABLE` → WARN.
- 2–3 invalid name scenarios: uppercase letter (rejected — the one
  rule genuinely different from every other resource's naming), empty,
  too long, leading `/`, invalid character.
- 1 determinism scenario (construct twice, compare).
- **If §4's vocabulary change is approved:** 2 new scenarios in
  `evals/datasets/architecture_intent_resolver_golden.json` — one
  resolving `STORAGE+{CONTAINER_REGISTRY}` to `EcrResourceSpec`, one
  `UNSPECIFIED`-interaction-pattern clarification counterpart. Zero
  existing scenarios need modification (§4).

## 14. Backward-compatibility strategy

Explicit regression evidence, mirroring Batch 26's own Task 12
checkpoint exactly:

- Full existing suites for `serverless_worker`, `api_lambda`,
  `api_lambda_dynamodb`, and every standalone resource
  (SQS/S3/DynamoDB/Lambda/API-Gateway) re-run **unmodified** and green
  — no existing file's assertions edited, only new entries/branches
  added.
- The exact CI-equivalent command
  (`pytest -m "not real_tool and not real_llm"`), not `tests/unit`
  alone — this is the explicit lesson from Batch 26's own CI failure
  (a non-real-tool `tests/integration` golden dataset carried an
  assumption `tests/unit` alone never exercised). Confirmed here in
  advance: no existing golden scenario's expected capability set
  collides with `{CONTAINER_REGISTRY}` (§4), so no pre-implementation
  fix is anticipated — but this must still be *run*, not assumed, at
  implementation time.

## 15. Exact dispatch/registration inventory (production)

| # | File | Function/Class/Constant | Reason | Coupling type |
|---|---|---|---|---|
| 1 | `domain/resource.py` | `ResourceType` | new `ECR` member | domain enumeration |
| 2 | `providers/aws/ecr/contract.py` (new) | `EcrResourceSpec`, `EcrImageTagMutability`, `EcrEncryptionSpec` | new contract | domain enumeration |
| 3 | `providers/aws/ecr/renderer.py` (new) | `EcrTerraformRenderer` | new renderer | rendering |
| 4 | `providers/aws/resource.py` | `AWSResourceSpec` union | widen union | domain enumeration |
| 5 | `providers/aws/resource.py` | `resource_type_of()` | new `case` arm | resolver-adjacent dispatch |
| 6 | `policies/platform.py` | new policy-ID constants | ECR-specific findings | policy |
| 7 | `policies/platform.py` | `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` | new entry | policy |
| 8 | `policies/platform.py` | `evaluate_platform_policies()` | new `case` arm | policy |
| 9 | `security/checkov_profiles.py` | `_PROFILES_BY_RESOURCE_TYPE` | new entry (Gate B) | security profile |
| 10 | `graph/workflow.py` | `_DEFAULT_TRUSTED_MODULE_DIRS` | new entry | rendering |
| 11 | `graph/workflow.py` | `_RESOURCE_KIND_DISPLAY_NAMES` | new entry | workflow (PR/commit text) |
| 12 | `persistence/checkpoints.py` | `_ALLOWED_WORKFLOW_TYPES` | 3 new entries (spec + 2 enums) | serialization |
| 13 | `cli/present.py` | `_architecture_label()` | new branch (fixes live bug, §1.10) | CLI/presentation |
| 14 | `cli/present.py` | `_component_lines()` | new branch (name/mutability/scan detail) | CLI/presentation |
| 15 | `intent/models.py` | `Capability` | new member *(if §4 approved)* | domain enumeration |
| 16 | `intent/models.py` | `AwsServiceHint` | new member *(if §4 approved, lower-stakes)* | domain enumeration |
| 17 | `intent/resolver.py` | `ArchitectureResolver.resolve()` | 2 new `case` arms *(if §4 approved)* | resolver |
| 18 | `intent/resolver.py` | `_build_ecr_spec()` (new) | new builder *(if §4 approved)* | resolver |
| 19 | `terraform/modules/ecr/*.tf` (new) | n/a | new trusted module | rendering |

**14 sites are unconditionally required (Option A alone); 5 more
(#15–19) only if the `Capability` vocabulary change in §4 is
approved** — i.e., ECR could theoretically exist as a
programmatically-constructible spec with zero LLM-reachable path, but
that would defeat the batch's own purpose, so #15–19 should be treated
as required in practice, contingent on the one open decision in §4/§20.

## 16. Exact dispatch/registration inventory (test/eval)

| # | File | Reason |
|---|---|---|
| 1 | `tests/unit/providers/aws/ecr/test_ecr_contract.py` (new) | contract validation |
| 2 | `tests/unit/providers/aws/ecr/test_ecr_renderer.py` (new) | renderer output |
| 3 | `tests/unit/providers/aws/test_resource_dispatch.py` | extend — `resource_type_of` |
| 4 | `tests/unit/providers/aws/test_renderer_dispatch.py` | extend — `AWSResourceRenderer` dispatch |
| 5 | `tests/unit/policies/test_ecr_platform_policies.py` (new) | ECR policy findings |
| 6 | `tests/unit/security/test_checkov_profiles.py` | extend (Gate B) |
| 7 | `tests/unit/test_resource_registration_consistency.py` | extend — the central cross-cutting registration test (§1's own precedent) |
| 8 | `tests/unit/persistence/test_checkpoints.py` (or a dedicated allowlist test, mirroring Batch 26's own new file) | isolated serializer round-trip |
| 9 | `tests/unit/cli/test_present.py` | extend — ECR-specific + generalized non-`"s3"`-fallback regression |
| 10 | `tests/unit/graph/test_workflow_ecr.py` (new) | mirrors `test_workflow_s3.py` |
| 11 | `tests/unit/intent/test_architecture_resolver.py` | extend *(if §4 approved)* |
| 12–15 | `evals/{datasets,scenarios,evaluators}/ecr_*` (4 new files) | golden dataset quartet |
| 16 | `evals/datasets/architecture_intent_resolver_golden.json` + its integration test's `_REQUIRED_SCENARIO_IDS` | 2 new scenarios *(if §4 approved)*, zero modified (§4) |
| 17 | `tests/integration/test_ecr_renderer_terraform.py` (new, Gate B) | real Terraform proof |
| 18 | `tests/integration/test_ecr_golden_real_tool_eval.py` (new, Gate B) | real Terraform+Checkov proof |
| 19 | `tests/integration/test_ecr_golden_evals.py` (new, Gate A — confirmed non-real-tool per Batch 26's own methodology correction) | deterministic golden suite |
| 20 | `tests/integration/test_ecr_workflow_persistence.py` (new, Gate B) | fresh-process durable HITL proof |

**Summary: 19 production sites (14 unconditional + 5 vocabulary-
contingent), 20 test/eval sites** (16 unconditional + 1 contingent + 3
purely additive-new-file quartets already counted). Comparable in
raw count to Batch 26's composition inventory (~11 production + ~14
test sites), but see §17 for why the *character* of the coupling
differs meaningfully.

### Silent-failure risk classification

| Site | Omission fails... |
|---|---|
| `ResourceType`/`AWSResourceSpec`/`resource_type_of` | **loudly** — `ValueError` at first dispatch attempt |
| `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` / `evaluate_platform_policies` | **loudly** — `KeyError`/fail-closed `raise` |
| `checkov_profile_for` | **loudly** — `ValueError`, confirmed by existing `checkov_profiles.py` design |
| `_DEFAULT_TRUSTED_MODULE_DIRS` | **loudly** — `KeyError` at render time |
| `_RESOURCE_KIND_DISPLAY_NAMES` | **loudly** — `KeyError` at commit-message time |
| **`_ALLOWED_WORKFLOW_TYPES`** | **silently** — confirmed real in Batch 26 Task 7: degrades to a raw `dict`, no exception, only detected by an explicit `type(...) is` assertion |
| **`cli/present.py` `_architecture_label`/`_component_lines`** | **silently** — confirmed real, pre-existing, live right now (§1.10): wrong label/empty detail lines, no exception, no test failure unless a dedicated test exists |
| `Capability`/resolver rows (if §4 approved) | **loudly in one direction** (an intent using the new capability with no resolver row falls to `UnsupportedArchitecture`, correctly fail-closed) — never silently mis-resolves |

Exactly two silent-failure classes exist in this entire inventory, and
both were already independently discovered and fixed once each in
Batch 26 for a different type (composition, not resource) — meaning
they are **structural**, recurring risks of this architecture's
current shape, not one-off oversights. This is the strongest evidence
in this design for §17.

## 17. Scalability/friction analysis

Comparing this ECR (resource) inventory against Batch 26's own
composition inventory, same repository, same session's discovery
discipline:

- **Volume is comparable** (~19 vs. ~11 production sites — resource
  addition is not obviously cheaper by site count alone, partly
  because ECR's own genuinely-new IAM/policy content adds sites a
  "thinner" resource might not have needed).
- **Character differs meaningfully.** Every one of Batch 26's
  composition-dispatch sites in `graph/workflow.py` required editing
  an existing `match`/`case` *expression* (three grouped `case
  ServerlessWorkerSpec() | ApiLambdaSpec() | ApiLambdaDynamoDbSpec():`
  arms to widen). **Zero** of ECR's sites require editing an existing
  `match`/`case` expression in `graph/workflow.py` — both required
  changes there are new `dict` entries. The `dict[ResourceType, X]`
  maps (`_DEFAULT_TRUSTED_MODULE_DIRS`, `_RESOURCE_KIND_DISPLAY_NAMES`,
  `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE`,
  `_PROFILES_BY_RESOURCE_TYPE`) are **already** a de facto micro-
  registry, keyed by `ResourceType` — this architecture already
  partially self-selected toward table-driven dispatch for the parts
  of it that are pure data, and kept `match`/`case` only for the parts
  that dispatch on Python's own concrete types (where structural
  pattern matching gives free exhaustiveness/type-narrowing a generic
  registry would have to reimplement or give up).
- **The two silent-failure sites (§16) are the real, repeated cost** —
  not the loud ones. Both recurred, independently, once each, in two
  different additions (a composition and now, by direct analysis, a
  hypothetical resource) in this same codebase.

## 18. Implementation gates proposal (design intent only — not the plan)

Mirrors Batch 26's own Gate A / Gate B split exactly, since the same
credential-free real-tool discipline applies identically:

- **Gate A (deterministic/offline):** contract, renderer (unit-level
  string assertions), resource/policy/checkpoint/CLI/workflow
  registration (sites #1–14, #12/#15–18 in §15/§16 excluding real-tool
  files), resolver vocabulary change if approved, golden-eval dataset
  quartet (deterministic evaluator only), docs.
- **Gate B (real Terraform + real Checkov, still credential-free):**
  renderer-terraform proof, empirical Checkov discovery + frozen
  profile, real-tool golden eval, fresh-process durable HITL proof.
- No Gate C/D/E — identical reasoning to Batch 26: nothing here ever
  touches real AWS credentials, GitHub writes, or OpenAI.

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
- A Composition/Resource Registry refactor — explicitly this batch's
  measurement subject, not its deliverable (§17/§20).
- Any change to Batch 25's OIDC/bootstrap boundary or Batch 26's three
  compositions — confirmed untouched throughout this design.

## 20. Unresolved human decisions

1. **The `Capability.CONTAINER_REGISTRY` vocabulary addition (§4)** —
   the single highest-leverage decision in this design. Without it,
   ECR can only ever be constructed by non-LLM callers, which likely
   defeats the batch's purpose but is technically possible to build
   and ship independently if you want the resource-registration
   friction data without the vocabulary risk.
2. **`EcrEncryptionSpec`'s shape** — mirror DynamoDB's minimalism (no
   `kms_key_id`, recommended) vs. mirror S3's (`kms_key_id: str |
   None`).
3. **Exact new policy-ID names and count** — proposed:
   `ECR_ENCRYPTION_REQUIRED` (hard), `ECR_SCAN_ON_PUSH_RECOMMENDED`,
   `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED` (both WARN) — needs sign-off
   like every prior batch's naming choices.
4. **Whether to build the generalized `_architecture_label`
   non-`"s3"`-fallback regression test (§12) now, alongside the ECR-
   specific one, or defer the generalization** — the ECR-specific fix
   is required either way; the broader test is a scope question.

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

**Conclusion:** the raw site count and the repeated-map observation are
real, but they don't yet demonstrate that a registry would *remove*
the two confirmed failure classes rather than relocate them. A Batch
28 registry is not ruled out, but implementing ECR first as designed
here (Option A, following the existing pattern exactly) — and
specifically watching whether the same two silent-failure classes
recur a *third* time — is stronger, cheaper evidence than committing to
a refactor now.

Not implemented this batch, per instruction.

---

No implementation performed. No implementation plan written. No
`terraform apply`/`destroy`. No AWS/OpenAI call. No GitHub mutation.
Batch 25's `bootstrap/aws-oidc`/`ci/aws_plan` and Batch 26's three
compositions confirmed untouched throughout this design (verified via
`git status`/`git diff` at the end of this session — clean).

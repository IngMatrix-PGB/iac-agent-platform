# DynamoDB Resource (Phase 2, Batch 17)

## Why DynamoDB, and why this document exists

Batch 16 proved the platform's design generalizes from one AWS
resource type (SQS) to a second (S3) without duplicating the platform.
Batch 17 adds DynamoDB as the *third* resource type specifically to
prove that adding one more resource is mostly additive — a new
`ResourceType` member, a new contract module, a new renderer, a new
trusted module, and small resource-keyed entries in a handful of
existing mappings, not a redesign of anything shared. See
`docs/roadmap.md` for the exact registration touchpoints this batch
discovered and used.

## The contract: `DynamoDBResourceSpec`

`iac_agent.providers.aws.dynamodb.contract.DynamoDBResourceSpec` is
the DynamoDB counterpart to `SQSResourceSpec`/`S3ResourceSpec` — a
strongly typed, Pydantic-validated model with no network calls, no AWS
SDK, no filesystem access:

```python
DynamoDBResourceSpec(
    name: str,
    environment: str | None = None,
    partition_key: DynamoDBKeySpec,
    sort_key: DynamoDBKeySpec | None = None,
    billing_mode: DynamoDBBillingMode = DynamoDBBillingMode.PAY_PER_REQUEST,
    point_in_time_recovery: bool = True,
    deletion_protection: bool = True,
    encryption: DynamoDBEncryptionSpec = DynamoDBEncryptionSpec(),
    tags: dict[str, str] = {},
)
```

### Hard invariants (unconstructible otherwise)

- **Encryption cannot be disabled.** `DynamoDBEncryptionSpec(enabled=False)`
  raises at construction — Phase 2 has no representation for an
  unencrypted table at all, mirroring SQS/S3's identical invariant.
- **Billing mode is always `PAY_PER_REQUEST`.** `DynamoDBBillingMode`
  has exactly one member; `PROVISIONED` is not representable at all,
  not merely defaulted away — exposing it would require read/write
  capacity controls this phase does not implement.

### Soft policy (WARN, not BLOCK)

- **Point-in-time recovery is recommended, not required.**
  `point_in_time_recovery=False` is a legitimate, constructible
  configuration — the security gate treats it as WARN, never BLOCK.
- **Deletion protection is recommended, not required.**
  `deletion_protection=False` is also legitimate (an ephemeral/demo
  table is a real use case) — WARN, never force-corrected back to
  `True`.

## Key model

```python
class DynamoDBKeyType(StrEnum):
    STRING = "S"
    NUMBER = "N"
    BINARY = "B"


class DynamoDBKeySpec(BaseModel):
    name: str
    type: DynamoDBKeyType
```

- A partition key is always required (a plain required Pydantic
  field — no separate "at least one key" invariant to hand-roll).
- A sort key is optional (`sort_key: DynamoDBKeySpec | None = None`).
- Key names must be non-empty, and the partition and sort key names
  must differ (`DynamoDBResourceSpec` rejects a duplicate pair at
  construction).
- `DynamoDBKeySpec` is the *only* source of a table's attribute
  definitions — the renderer and trusted module never infer or accept
  an arbitrary table-field attribute beyond the partition key and
  (if present) the sort key.

## Table name validation

Verified against the current AWS DynamoDB "Naming rules" documentation
before implementation (not assumed from training data or an older
ruleset):

- 3–255 characters.
- Letters (`a-z`, `A-Z`), digits, underscore (`_`), hyphen (`-`), and
  period (`.`) only — case-sensitive, UTF-8 encoded.
- No adjacent-character restriction, no lowercase-only requirement, no
  reserved prefix/suffix list — DynamoDB's naming rules are
  meaningfully simpler than S3's.

Unlike S3, DynamoDB table names are scoped per AWS account+region, not
globally unique — there is no "syntactically valid but unavailable"
caveat to document here the way there is for S3 buckets.

## Billing mode: PAY_PER_REQUEST only

Batch 17 supports exactly one billing mode. Provisioned capacity
(`read_capacity`/`write_capacity`), autoscaling, and any capacity
controls are explicit Phase 2 non-goals, deferred to a future phase
that would also need to design the read/write-capacity contract
surface this batch deliberately does not add.

## Encryption: AWS-owned key only (customer-managed KMS deferred)

Every table is encrypted (`server_side_encryption { enabled = true }`
is unconditional in the trusted module). Customer-managed KMS support
was evaluated and **deferred** — a concrete, empirically-confirmed
provider-semantics limitation, not an oversight:

`aws_dynamodb_table`'s real schema (`server_side_encryption.kms_key_arn`)
requires a full KMS key or alias **ARN**, and rejects the bare
alias-name/bare-key-ID forms that this project's shared
`iac_agent.providers.aws.kms.validate_kms_key_id` validator (and
S3's/SQS's own `kms_key_id` fields) otherwise accept. Confirmed via a
real `terraform plan`, which failed with `"invalid ARN: arn: invalid
prefix"` for a bare alias name. Rather than bolt on a second,
DynamoDB-only KMS validator for this batch, `DynamoDBEncryptionSpec`
has no `kms_key_id` field at all — a future phase can add one once a
DynamoDB-appropriate ARN-only validator is designed.

## Point-in-time recovery and deletion protection

Both default to `True` and can be explicitly set to `False` — each is
a real, legitimate configuration choice surfaced as a WARN by the
platform policies below, never rejected at the contract layer and
never silently forced back to `True`.

## The Terraform module: `terraform/modules/dynamodb`

A small, trusted module — never a raw `aws_dynamodb_table` block in
the renderer's own output, only a `module` invocation. Verified
empirically against the real AWS provider (6.64.0) schema before
writing `main.tf` (via `terraform providers schema -json`), not
assumed:

- `aws_dynamodb_table.this` — `billing_mode` hardcoded to
  `"PAY_PER_REQUEST"` (no variable for it at all); `hash_key`/
  `range_key` (the latter `null` when no sort key); exactly one or two
  `attribute` blocks (partition key, plus a `dynamic "attribute"` block
  for the sort key only when present); `point_in_time_recovery { enabled
  = var.point_in_time_recovery }`; `server_side_encryption { enabled =
  true }` (unconditional, no `kms_key_arn` argument at all —
  AWS-owned-key encryption only); `deletion_protection_enabled =
  var.deletion_protection` (the exact provider attribute name — not
  `deletion_protection`, confirmed via the real schema); `tags`.

**Explicitly out of scope for Phase 2** (deferred, not forgotten):
provisioned capacity/autoscaling, Global Secondary Indexes, Local
Secondary Indexes, DynamoDB Streams, Global Tables, DAX, TTL, table
classes, import/export, backups beyond PITR, and resource policies.

Real `terraform fmt`/`init -backend=false`/`validate`/`plan` runs (see
`tests/integration/test_dynamodb_renderer_terraform.py`) confirm the
secure baseline always plans exactly one resource, a create, no AWS
credentials required.

### Module outputs

Only `table_name` and `table_arn` — no `table_id` (DynamoDB's `id`
attribute equals the table name, so a separate output would be
redundant, not genuinely useful).

## Platform policy

`iac_agent.policies.platform.evaluate_platform_policies` dispatches on
resource type and evaluates three DynamoDB-specific policies plus the
one platform-wide policy shared with SQS/S3:

| Policy ID | Outcome |
|---|---|
| `DDB_ENCRYPTION_REQUIRED` | PASS (encryption is a hard invariant, so this is defense-in-depth) |
| `DDB_PITR_RECOMMENDED` | PASS if enabled, WARN if disabled — never BLOCK |
| `DDB_DELETION_PROTECTION_RECOMMENDED` | PASS if enabled, WARN if disabled — never BLOCK |
| `TF_NO_DESTRUCTIVE_CHANGES` | shared with SQS/S3 — evaluated once, resource-agnostic |

## Checkov: one documented scope exclusion, not a suppressed weakness

Running real Checkov (Checkov 3.3.13) against the secure DynamoDB
baseline (1 resource) reports exactly one finding:

| Check | What it wants |
|---|---|
| `CKV_AWS_119` | "Ensure DynamoDB Tables are encrypted using a KMS Customer Managed CMK" |

This corresponds precisely to the one feature this batch explicitly
deferred (see "Encryption" above) — not a defect in the secure
baseline, and not a false positive. Since every Checkov-reported failed
check maps unconditionally to `PolicyStatus.BLOCK` (no WARN pathway
exists for Checkov findings), leaving this unskipped would mean no
DynamoDB request could ever reach human approval.

Per this batch's own "classify the finding, then STOP and report a
declared non-goal before adding a skip" instruction, this was surfaced
to the project owner via `AskUserQuestion` before being added — the
same discipline followed for S3's four skips in Batch 16. The decision:
add `CKV_AWS_119` to a DynamoDB-specific `CheckovScanProfile`
(`iac_agent.security.checkov_profiles.checkov_profile_for`). Real scan
result with the skip applied: 3 passed, 0 failed, 0 skipped
(`summary.skipped` does not count CLI `--skip-check` exclusions in
this Checkov version — verified empirically, not assumed).

## Workflow integration

`iac_agent.graph.workflow.build_iac_workflow` is the resource-neutral
entry point — a `DynamoDBResourceSpec` flows through the identical
eight nodes an `SQSResourceSpec`/`S3ResourceSpec` does. Only two things
are resource-aware at all: `render_terraform` (selects the DynamoDB
renderer and trusted module directory) and the PR/commit text in
`source_control`. One concrete third-resource wrinkle was found and
fixed here: the PR/commit "resource kind" label previously derived from
`resource_type_of(spec).value.upper()`, which happened to be correct
for SQS ("SQS") and S3 ("S3") but would have produced "DYNAMODB"
(all-caps) instead of the proper product name "DynamoDB". Fixed with a
small explicit `ResourceType`-keyed display-name mapping in
`iac_agent.graph.workflow`, not a broader redesign.

There is no `build_dynamodb_workflow` — `build_iac_workflow` is the one
shared entry point every resource type (including SQS and S3, via the
`build_sqs_workflow` compatibility wrapper) ultimately goes through.

## No customer-managed KMS, still no `terraform apply`

Nothing about DynamoDB support changes this project's central safety
property: `TerraformRunner` has no `apply` method anywhere, no AWS
mutation of any kind ever occurs, and a GitHub pull request remains the
terminal artifact for a DynamoDB request exactly as it is for SQS/S3.

## Known application-layer debt (unchanged scope this batch)

`iac_agent.app.service.Phase1Application` and the composition layer
remain SQS-only (tracked since Batch 16 — see `docs/roadmap.md`).
DynamoDB, like S3, does not go through that layer in this batch; every
DynamoDB test in this batch calls `build_iac_workflow` directly. This
batch did not need to touch the application layer at all — DynamoDB's
addition never required generalizing any "blocking assumption" there,
since the graph layer it actually needs was already resource-neutral
from Batch 16 onward.

# Design Spec: AWS Plan Boundary / GitHub OIDC Foundation (Batch 25)

Status: **DESIGN ONLY — no implementation in this document.**
Discovery base: `origin/main` `460d717` (PR #4 Batch 23 + PR #5 Gate D demo
artifact, both merged). **`feat/batch24-demo-cli` — the actual CLI/
composition implementation (Tasks 1–12) — is NOT yet merged to `main`.**

**Golden rule, unchanged and reframed for this batch: the security claim
is not "`terraform plan` is read-only." The security claim is "the AWS
identity used for planning lacks mutating permissions, so an attempted
provider-side mutation is denied by AWS authorization."**

---

## 0. Two critical findings (read before anything else below)

### 0.1 The currently-generated Terraform is architecturally incapable of a real AWS plan

`src/iac_agent/providers/aws/terraform_render.py:130-131` unconditionally
emits, into every generated `provider "aws" {}` block:

```hcl
skip_credentials_validation = true
skip_requesting_account_id  = true
skip_metadata_api_check     = true
skip_region_validation      = true
```

paired with `src/iac_agent/graph/workflow.py:204`:

```python
_PLAN_ENV_OVERRIDES = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}
```

used at `src/iac_agent/graph/workflow.py:417`
(`terraform_runner.plan(workspace, env_overrides=_PLAN_ENV_OVERRIDES)`).
This is confirmed, unmodified, working-as-designed behavior — it is
*why* the existing pipeline runs in CI today with zero AWS credentials
(`README.md`'s own "Terraform validation/plan (credential-free)" claim).
The actual merged demo artifact (`generated/req-20260926T215226Z/main.tf`,
merged via PR #5) has this exact provider block.

**Consequence:** running `terraform plan` against this exact,
byte-identical generated artifact — the one a real PR actually contains
today — will **never** call any real AWS API, no matter what OIDC/STS
credentials CI supplies. The plan literally does not attempt to
authenticate. Wiring up OIDC without addressing this proves nothing: CI
would "succeed" whether or not the trust boundary works at all.

This is a genuine, load-bearing contradiction with the assumption
(implicit throughout the authorization message) that Batch 25 plans
"the same generated Terraform artifact that comes out of a PR." I am
not silently resolving it. Three honest options, none implemented here:

- **Option 1 (recommended for Batch 25):** keep the generated artifact
  byte-identical (it is explicitly "GENERATED FILE — do not edit by
  hand," and changing renderer output is production-code work, out of
  scope this batch). The AWS real-plan CI job supplies a Terraform
  **override file** (`_override.tf`, Terraform's own native
  file-merge mechanism) *outside* the generated directory's tracked
  content, at plan time only, replacing just the `provider "aws" {}`
  block's `skip_*` flags and region for that one CI invocation. Nothing
  in `generated/<request_id>/` changes; nothing in `src/` changes;
  the override file lives in `.github/` or a new `ci/` directory,
  never touched by the renderer.
- **Option 2:** modify the renderer to make the skip-flags conditional
  on an environment variable. This is a real production-code change —
  explicitly out of scope for this design-only batch, and it would
  touch the one thing every prior batch has kept frozen ("GENERATED
  FILE — do not edit by hand" / deterministic renderer output).
- **Option 3:** decouple the claims. Batch 25 proves the OIDC→STS→
  least-privilege boundary against a small, dedicated, hand-written
  Terraform fixture that lives in the bootstrap/test plane (never the
  agent's own renderer output), and a *separate*, later batch decides
  whether/how to connect that boundary to the agent's real generated
  artifacts.

I recommend **Option 1** and have designed §6/§10 around it, but this is
a human decision point, not something to assume settled.

### 0.2 A `terraform plan` of brand-new resources against real AWS likely needs almost no IAM permissions at all

Every resource in the current serverless-worker composition
(`aws_sqs_queue`, `aws_sqs_queue.dlq`, `aws_dynamodb_table`,
`aws_iam_role`, `aws_cloudwatch_log_group`, `aws_iam_role_policy` ×3,
`aws_lambda_function`, `aws_lambda_event_source_mapping`) is being
created for the first time — there is no prior Terraform state (Batch
25 explicitly excludes remote state, §F) and no `data` source in the
generated files that queries real AWS (the two `data
"aws_iam_policy_document"` blocks are computed locally, not API calls).
Terraform's refresh step only reads resources already present in state;
for an all-new plan, the AWS provider's only real network call is
typically the one-time `sts:GetCallerIdentity` it performs during
provider configuration (unless skipped, per §0.1) to resolve
account/partition for ARN construction — **not** `sqs:Get*`,
`lambda:Get*`, `dynamodb:Describe*`, or `iam:Get*`.

This means the "candidate baseline" families in the authorization
message (§D) are a reasonable **starting hypothesis** for a *future*
scenario involving existing/refreshed resources, but for *this specific
vertical slice* (brand-new proposal, no backend, no refresh target),
the empirically-discovered policy in §E may turn out to be dramatically
smaller than the candidate list — possibly close to just
`sts:GetCallerIdentity`. I am stating this as a structural hypothesis
to be confirmed by the discovery loop (§E), not as a verified fact — no
real AWS call has been made in producing this document.

---

## 1. Repository findings

| Question | Answer | Evidence |
|---|---|---|
| Current GitHub Actions workflows | One: `.github/workflows/ci.yml` | file read in full |
| Workflow triggers | `pull_request` (branches: `[main]`) and `push` (branches: `[main]`) | `ci.yml:3-6` |
| Current workflow permissions | `contents: read` only, no `id-token` anywhere | `ci.yml:8-9` |
| Jobs | `quality` (ruff + `terraform fmt -check`), `tests` (deterministic pytest), `tool-validation` (`real_tool` pytest, needs real terraform+checkov binaries) | `ci.yml` |
| Terraform version pinned in CI | `1.16.1` | `ci.yml` (`hashicorp/setup-terraform@v3`), matches local `terraform version` |
| AWS provider version | `~> 6.0` constraint (`versions.tf`), resolves to `6.66.0` locally today | `generated/req-20260926T215226Z/versions.tf` (on `main` via PR #5); `artifacts/*/. terraform.lock.hcl` |
| `TerraformRunner` capabilities | `fmt`, `init`, `validate`, `plan`, `show_json` only | `src/iac_agent/execution/terraform_runner.py:201-256` (full method list) |
| `apply`/`destroy` existence | Confirmed absent everywhere; the module's own docstring states it explicitly | `terraform_runner.py:9` ("`apply`/`destroy` do not exist here"); repo-wide grep for `terraform apply`/`terraform destroy` invocations returns none outside comments/tests asserting absence |
| Generated resources for serverless-worker composition | SQS queue + DLQ, DynamoDB table, Lambda function + execution role + log group, event source mapping, 2 inline IAM role policies (SQS consume, DynamoDB write) | `generated/req-20260926T215226Z/main.tf`, `terraform/modules/{sqs,dynamodb,lambda}/main.tf` |
| Lambda execution-role IAM shape | One `aws_iam_role.this` (assume-role trust doc computed locally), one `aws_iam_role_policy.logs` (CloudWatch Logs only) — no AWS-managed policy, no wildcard | `terraform/modules/lambda/main.tf:34-79` |
| Credential-free plan mechanism | `skip_credentials_validation`/`skip_requesting_account_id`/`skip_metadata_api_check`/`skip_region_validation = true` in every generated provider block, paired with placeholder `AWS_ACCESS_KEY_ID=test`/`AWS_SECRET_ACCESS_KEY=test` env override at plan time | `src/iac_agent/providers/aws/terraform_render.py:130-131`; `src/iac_agent/graph/workflow.py:204,417` — **see §0.1** |
| Existing `real_tool` tests | 31 files under `tests/integration/`, covering every resource/composition renderer + workflow + HITL + CLI real-tool path | file listing captured |
| Existing CLI real-tool path | `tests/integration/test_cli_real_tool.py` (Batch 24 Task 12) — real Terraform+Checkov, fake GitHub transport, fake interpreter | already read this batch |
| Existing Checkov path | `CheckovAdapter` (real binary, `pip install checkov==3.3.13` in CI's `tool-validation` job) | `ci.yml` |
| AWS provider placeholder credentials already present | Yes — see §0.1 | — |
| Where CI would find Batch-24-generated PR Terraform | `generated/<request_id>/*.tf`, committed directly into the PR by `publish_change` (proven live by PR #5) | `generated/req-20260926T215226Z/` on `main` |
| Is the current PR artifact directly plan-able by GitHub Actions, or does it need an application-boundary adaptation | Directly plan-able **only if §0.1 is resolved** (Option 1/2/3) — otherwise plan trivially "succeeds" without ever calling AWS | §0.1 |
| Is `feat/batch24-demo-cli` (the actual CLI) merged to `main`? | **No.** Confirmed via `git merge-base --is-ancestor feat/batch24-demo-cli origin/main` → false; `src/iac_agent/cli/` does not exist on `origin/main` at all | direct check this session |

**Sequencing note (not a Batch 25 blocker, but a real dependency):**
today, the only way a `generated/<request_id>/` directory reaches a PR
in production is via the (unmerged) Batch 24 CLI or an ad-hoc script
like the one used for Gate D. Batch 25's CI design (§6/§10) should
detect "generated Terraform changed in this PR" structurally (by path),
not by assuming any particular producer — that keeps Batch 25 correct
regardless of when Batch 24 merges.

---

## 2. Current CI/Terraform execution map

```
pull_request → main  ─┬─→ quality         (ruff, terraform fmt -check)
push → main          ─┤
                       ├─→ tests           (pytest, deterministic, no terraform/checkov/openai/aws)
                       └─→ tool-validation  (pytest -m real_tool: REAL terraform+checkov, still
                                             credential-free per §0.1, never AWS)
```

No job today requests an OIDC token, uses `id-token`, or touches AWS in
any real sense.

---

## 3. Batch 25 trust-boundary diagram

```
BOOTSTRAP / CONTROL PLANE  (separate from iac-agent-platform)
        │
        ├── GitHub Actions OIDC Provider (AWS IAM identity provider)
        ├── IaCPlanRole
        │     ├── trust policy: aud=sts.amazonaws.com, sub=<verified, §5>
        │     └── permissions policy: least-privilege, empirically derived (§7-9)
        │
   (manually/bootstrap-applied by the repo owner; iac-agent-platform
    only ever consumes AWS_PLAN_ROLE_ARN as configuration)
        │
        │ sts:AssumeRoleWithWebIdentity  (short session, OIDC JWT)
        ▼
──────────────────────── TRUST BOUNDARY ────────────────────────
        ▲
        │
iac-agent-platform — GitHub Actions, event: pull_request (never pull_request_target)
        │
        ├── existing jobs (quality/tests/tool-validation) — unchanged, still AWS-independent
        │
        └── new job: aws-plan  [OPT-IN: label `aws-plan` + authorized-actor/context condition]
                 │  permissions: id-token: write (this job ONLY), contents: read
                 ├── terraform init
                 ├── terraform validate
                 ├── terraform plan   (against real AWS, via assumed IaCPlanRole — §0.1 resolution required)
                 └── Checkov
                        │
                        ▼
                    CI result (visible in the PR, no apply, no destroy, no AWS mutation possible)
```

---

## 4. Confirmed architectural invariants

All of §A–H from the authorization message are confirmed compatible
with repository evidence and adopted as locked constraints for Batch
25, with one addition surfaced by discovery:

- **A (separate bootstrap plane):** confirmed sound; mirrors the
  project's existing "the agent never controls what constrains it"
  pattern (the agent never manages its own `GITHUB_TOKEN`'s scope
  either — same principle, extended to AWS).
- **B (OIDC trust, no hardcoded `sub`):** confirmed — see §5, this
  repo predates the July-2026 immutable-subject default and has not
  (as far as I can determine without running the debugger workflow)
  opted into it, but that must be *verified*, not assumed.
- **C (short-lived STS session, no static keys):** confirmed
  compatible; nothing in the current composition stores or reads
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` as a GitHub secret today
  — only the graph's own internal placeholder (§0.1), which is
  unrelated to real credentials.
- **D (least-privilege, empirically derived):** confirmed as the right
  process; see §0.2 for why the final policy may be smaller than the
  candidate list.
- **E (discovery loop, no ReadOnlyAccess as final state):** confirmed
  sound methodology.
- **F (no remote state):** confirmed — no backend config exists
  anywhere in this repo today; adding one would be new, out-of-scope
  work.
- **G (opt-in via label + authorized context):** confirmed sound; see
  §11 for the additional GitHub-native layer.
- **H (no apply/destroy):** confirmed — `TerraformRunner` has no such
  methods (§1), and nothing in this design adds any.
- **New invariant surfaced by §0.1:** *the generated Terraform artifact
  itself must not be silently modified to enable this batch.* Any
  mechanism that makes real-AWS planning possible must not touch
  `src/iac_agent/providers/aws/terraform_render.py` or the "generated
  file — do not edit by hand" contract, without a separate, explicit
  human decision to do so.

---

## 5. OIDC claim-discovery design

**Goal:** determine this repository's actual emitted `aud`/`sub`
before writing any AWS trust policy — never assume the legacy format.

**Method (GitHub's own documented tool, confirmed via current docs
fetch this session):** the `github/actions-oidc-debugger` action
visualizes the claims a workflow run would send, without ever
integrating with a cloud provider and without exposing the raw JWT.
Concretely:

1. Add a **temporary, throwaway** workflow (never the real `ci.yml`)
   that runs `github/actions-oidc-debugger` on a `pull_request` trigger
   from this exact repository, requesting `id-token: write` only in
   that one temporary job.
2. Capture only the **sanitized, decoded claim fields** the action
   prints (`aud`, `sub`, `repository`, `repository_owner`,
   `event_name`, `ref`) — never the encoded JWT string itself.
3. Confirm whether `sub` is the legacy
   `repo:IngMatrix-PGB/iac-agent-platform:pull_request` or the
   immutable `repo:IngMatrix-PGB@<owner_id>/iac-agent-platform@<repo_id>:pull_request`
   shape.
4. Confirm the workflow does **not** reference a GitHub Environment
   (it currently doesn't — `ci.yml` has no `environment:` key anywhere)
   — if a future job added one, the `sub` shape changes to include
   `environment:<name>` instead of `pull_request`, and the trust policy
   would need updating.
5. Delete the temporary debugger workflow once claims are recorded.
   The AWS trust policy is written from the recorded claim, never from
   assumption.

This step requires adding a temporary workflow file, which is a
repository change — it is **not executed in this design-only
document**; it is the first concrete action of the implementation
plan, requiring separate authorization (§19).

---

## 6. Bootstrap-plane design

Minimum resources, owned entirely outside `iac-agent-platform`:

- One `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`
  (thumbprint/audience per AWS's current documented values — AWS
  manages GitHub's OIDC thumbprint automatically today for this
  provider type; verify current AWS guidance at bootstrap-apply time,
  not assumed here).
- One `aws_iam_role` (`IaCPlanRole`) with:
  - Trust policy: `Condition` on `token.actions.githubusercontent.com:aud == sts.amazonaws.com` and `token.actions.githubusercontent.com:sub == <value confirmed in §5>`, both `StringEquals`.
  - Permissions policy: per §7–9, attached as an inline or managed
    customer policy — never `AdministratorAccess`/`ReadOnlyAccess`/`PowerUserAccess`.
  - A maximum session duration set short (e.g. 900–1800s) — just
    enough for `init`+`validate`+`plan`+Checkov.

`iac-agent-platform` needs to know exactly one new piece of
non-secret configuration: the role ARN (e.g. `AWS_PLAN_ROLE_ARN`),
referenced by the new CI job only (§10). No secret value is required —
`aws-actions/configure-aws-credentials` resolves the OIDC exchange
using the ARN plus GitHub's own OIDC token, nothing stored.

The bootstrap module/repository itself is out of scope to author here
(separate repository, likely alongside other account-level bootstrap
concerns already tracked in this platform's ecosystem) — this design
only specifies what it must produce and how the workload repo consumes
it.

---

## 7. Candidate `IaCPlanRole` policy matrix

| Family | Candidate actions | Status |
|---|---|---|
| STS | `sts:GetCallerIdentity` | **A — near-certain requirement** (provider init, if §0.1 skip-flags are overridden) |
| SQS | `GetQueueAttributes`, `GetQueueUrl`, `ListQueueTags`, `ListQueues` | **B — requires empirical discovery**; per §0.2, may not be exercised at all for a from-scratch plan |
| Lambda | `GetFunction`, `GetFunctionConfiguration`, `GetFunctionCodeSigningConfig`, `GetPolicy`, `ListTags`, `ListVersionsByFunction` | **B** — same caveat |
| DynamoDB | `DescribeTable`, `DescribeContinuousBackups`, `DescribeTimeToLive`, `ListTagsOfResource` | **B** — same caveat |
| IAM | `GetRole`, `GetRolePolicy`, `ListRolePolicies`, `ListAttachedRolePolicies` | **B** — same caveat; needed only if the provider ever reads an *existing* execution role (not the case for a brand-new one) |

None of these are approved as a final policy. §8/§9 are authoritative
about what happens next.

---

## 8. Permissions requiring empirical discovery

Per §0.2, the discovery loop (§E of the authorization, adopted
unchanged) must be run against a **real** `terraform plan` invocation
(with §0.1 resolved) before any family in §7 is added beyond
`sts:GetCallerIdentity`. Expected outcome, stated as a hypothesis: the
loop converges quickly (1–2 iterations) because there is no existing
state to refresh and no AWS-querying `data` source in the current
generated composition. If discovery instead reveals additional calls
(e.g., the AWS provider internally validating an ARN format against a
live IAM lookup, which is plausible but not confirmed), each is added
one at a time, per the loop, never in bulk.

## 9. Explicitly forbidden AWS permissions

Adopted verbatim from the authorization message, confirmed compatible
with the actual generated resources (§1) — none of the forbidden
actions are needed by any resource in the current composition:

```
iam:PassRole                iam:PutRolePolicy
iam:CreateRole               iam:AttachRolePolicy
iam:UpdateAssumeRolePolicy   sts:AssumeRole
<service>:Create*/Update*/Delete*/Put*  (unless discovery proves an
   apparently-read operation is genuinely necessary and non-mutating —
   in which case STOP and report, per the authorization's own rule)
```

---

## 10. GitHub Actions design

**Recommendation: one new job (`aws-plan`) inside the existing
`.github/workflows/ci.yml`, not a new workflow file, not a reusable
workflow.**

Rationale, from repository evidence: `ci.yml` already establishes the
concurrency-group/trigger pattern this job needs to share (same
`pull_request` event, same `main` target); a second workflow file would
duplicate the trigger/concurrency block for no structural benefit, and
a reusable workflow is unwarranted complexity for a single consuming
job in a single repository (the authorization's own "avoid architecture
for architecture's sake" instruction).

```yaml
# conceptual only — not implemented in this document
jobs:
  # ...existing quality/tests/tool-validation jobs, unchanged...

  aws-plan:
    name: AWS Plan (opt-in)
    runs-on: ubuntu-latest
    if: >
      contains(github.event.pull_request.labels.*.name, 'aws-plan')
      && <authorized-actor/context condition, §11>
    permissions:
      id-token: write   # only this job gets it
      contents: read
    needs: [quality]     # do not burn an OIDC session on a PR that fails basic checks
    steps:
      - checkout
      - configure-aws-credentials (role-to-assume: AWS_PLAN_ROLE_ARN, audience: sts.amazonaws.com)
      - terraform init/validate/plan on generated/<request_id>/  (with §0.1's override file)
      - checkov
```

`needs: [quality]` is a cheap, structural way to avoid spending an AWS
session on a PR that doesn't even pass `ruff`/`terraform fmt` — not
required, but low-cost and sensible.

---

## 11. Opt-in/authorization design

Three layers, all required together (defense in depth, not
alternatives):

1. **Label `aws-plan`** — on a public repo, GitHub already restricts
   who can attach labels to Triage/Write-permission collaborators; an
   external fork PR's own author cannot self-label.
2. **Authorized-actor/context condition** — an explicit allowlist
   check (e.g., `github.event.pull_request.user.login` or the actor
   who applied the label, against a small, human-maintained list),
   independent of GitHub's own label ACL, as defense-in-depth against
   any edge case in that ACL or a compromised collaborator account
   being tricked into labeling a malicious PR.
3. **Repository setting: "Require approval for outside
   collaborators"** (Settings → Actions → General) — a GitHub-native,
   platform-level gate requiring a maintainer to explicitly approve
   the *entire workflow run* for first-time/outside contributors,
   before *any* job (not just `aws-plan`) executes. This is
   independent of and redundant with layers 1–2, not a replacement for
   either.

---

## 12. Public-repository/fork threat model

| Threat | Analysis |
|---|---|
| Fork PR modifies the workflow itself | `pull_request` (never `pull_request_target`) already runs with the workflow definition from the PR's own head ref, but with GitHub's default reduced token permissions for fork PRs (no secrets, no elevated `GITHUB_TOKEN`) — however OIDC `id-token: write` is a workflow-level permission grant, not a secret, and **is** available to fork PR runs unless additionally gated. This is exactly why layers §11.1–3 exist. |
| Fork PR modifies Terraform | Same job would then `terraform init/plan` attacker-controlled `.tf` content with the assumed role's credentials in the job's environment during that step. |
| Malicious provider configuration | An attacker-controlled `provider` block (or a pinned malicious/typosquatted provider source) could execute arbitrary code during `terraform init`/`plan` (Terraform providers are ordinary binaries). This is the single largest real risk in this whole design — least-privilege IAM limits *what AWS API calls* succeed, but does not prevent a malicious provider binary from reading the process environment (where the temporary AWS credentials live) and exfiltrating them over the network before ever calling AWS. |
| External `data`/`local-exec`-style behavior | Same category — Terraform's own extensibility is the attack surface, not just AWS permissions. |
| Credential exfiltration | Even read-only STS credentials, if exfiltrated, allow real reconnaissance of the AWS account (resource enumeration, tags, account structure) — the design must not claim these credentials are harmless if leaked. |
| Maintainer accidentally labels an untrusted PR | The one scenario least-privilege IAM *does* meaningfully mitigate: even if a maintainer mislabels a malicious PR, the assumed role cannot mutate AWS — worst case is read-only reconnaissance + a runtime credential-exfiltration risk during the ~15–30 min session window, not infrastructure damage. |
| `pull_request` vs `pull_request_target` | Confirmed `pull_request` throughout this design; `pull_request_target` would run with the *base* repo's elevated token against attacker code — never used here. |
| Overly broad OIDC trust | Mitigated by §5's verify-before-freeze discipline and exact `sub` match (`StringEquals`, not `StringLike` with a wildcard). |
| Overly broad AWS permissions | Mitigated by §7–9's empirical, additive-only derivation. |
| Compromised workflow dependency/action | `github/actions-oidc-debugger`, `aws-actions/configure-aws-credentials`, `hashicorp/setup-terraform` should be pinned to a specific commit SHA (not a floating tag) in the eventual implementation — noted here as a requirement, not yet done. |
| Session lifetime | Short `DurationSeconds` (§6) bounds the exfiltration-usefulness window. |
| Arbitrary Terraform supplied by PR | This is the credential-exfiltration risk above, restated — the honest mitigation is the three-layer human gate (§11), not a technical guarantee that untrusted Terraform code is safe to plan with real credentials attached. |
| Head-repo restriction | **Recommended additional condition:** gate `aws-plan` on `github.event.pull_request.head.repo.full_name == github.event.pull_request.base.repo.full_name` in addition to label+actor — i.e., refuse to run the AWS-plan job at all for PRs originating from a fork, regardless of label/actor, and only allow it for branches pushed directly to this repository by a collaborator. This closes the "arbitrary fork-controlled Terraform" risk at the structural level rather than relying solely on human judgment about labels. |

**Explicit statement per the authorization's own requirement:**
read-only AWS credentials are not harmless if exfiltrated — they permit
account reconnaissance. This design's actual safety property is
narrower and honest: *mutation is denied by IAM even in the worst case
of a maliciously-labeled fork PR*; *credential exfiltration itself* is
mitigated by the head-repo restriction, the three-layer opt-in gate,
and short session duration, not eliminated outright.

---

## 13. Deterministic test strategy (offline, no OIDC/AWS/network)

All of these are structural/source-inspection tests, mirroring this
repo's existing `ast`-based isolation-proof convention
(`tests/unit/intent/test_multi_provider_boundary_isolation.py`,
`tests/unit/app/test_intent_application.py`):

- Parse `.github/workflows/ci.yml` (and any new workflow file) and
  assert: event is `pull_request` (never `pull_request_target`
  anywhere in the file); `id-token: write` appears only on the
  `aws-plan` job's own `permissions` block, not at workflow level or
  on any other job; the `aws-plan` job's `if:` condition references
  both the `aws-plan` label and a head-repo/base-repo equality check.
- `TerraformRunner` still has no `apply`/`destroy` method (already
  proven by Batch 24's `test_no_apply.py` — extend, don't duplicate).
- If a bootstrap Terraform module is added to *this* repository for
  reference/documentation purposes (read-only reference copy, not the
  authoritative applied source): assert it is never invoked by
  `TerraformRunner`, never referenced by any `real_tool` test as
  something this repo applies.
- A policy-matrix source file (e.g. a small JSON/HCL fixture
  documenting the frozen `IaCPlanRole` permission set once empirically
  derived) — a test asserting the forbidden-action list (§9) is
  disjoint from the frozen allow-list, structurally, on every CI run
  (regression guard against permission creep).
- No test in this suite requires network access, AWS credentials, or a
  real OIDC token — all real-AWS/OIDC verification is separately
  marked (§14).

---

## 14. Real AWS validation strategy

- A new pytest marker, e.g. `real_aws_plan`, excluded from default CI
  exactly like `real_tool`/`real_llm` are today (`pyproject.toml`'s
  `markers` list, same pattern).
- Positive path: authorized PR + `aws-plan` label → OIDC → STS →
  `IaCPlanRole` → real `terraform plan` succeeds, observed via the
  actual CI run's own output (not re-derived offline).
- Negative path (per the authorization's own instruction, **never**
  proven destructively): IAM policy simulation
  (`iam:SimulatePrincipalPolicy`, a genuinely read-only AWS API) run
  against a representative mutating action (e.g. `sqs:CreateQueue`)
  and asserting the simulated decision is `implicitDeny` — this is a
  safe, non-destructive, structural proof that the frozen policy lacks
  mutation authority, without ever attempting the mutation for real.

---

## 15. Video-ready acceptance criteria

1. IaC Agent (or a manually-triggered equivalent, pending Batch 24
   merge) opens a PR with generated Terraform.
2. `quality`/`tests`/`tool-validation` pass exactly as today.
3. A maintainer adds the `aws-plan` label to a PR from a
   same-repository branch (not a fork).
4. The `aws-plan` job appears, requests an OIDC token, and the CI log
   shows GitHub issuing it and AWS STS returning temporary credentials
   (session details visible, never the credential values themselves).
5. `terraform init`/`validate`/`plan` run against real AWS and the plan
   output is visible in the CI log/PR.
6. Checkov output is visible.
7. The PR/README/CI summary states explicitly: no static AWS keys, no
   `apply`, no `destroy`, no AWS mutation authority — and (once §14's
   policy-simulation check exists) that check's PASS result is part of
   the visible evidence.

---

## 16. Exact Batch 25 scope

GitHub OIDC provider + `IaCPlanRole` bootstrap design; one new opt-in
`aws-plan` CI job; empirically-derived least-privilege IAM policy for
the current serverless-worker vertical slice; OIDC claim verification
step; fork/public-repo threat mitigations; deterministic + real-AWS
test strategy. Resolution of §0.1 (how the real plan reaches the
existing generated artifact without modifying the renderer) is treated
as in-scope *design* work but is the first thing requiring explicit
human sign-off before an implementation plan is written.

## 17. Non-goals

Everything in the authorization's §11 (unchanged): `terraform
apply`/`destroy`, AWS deployment, remote Terraform state/S3
backend/state locking, production workload mutation, FastAPI, Next.js,
additional LLM providers, Kubernetes, multi-account deployment, a
generalized deployment engine, self-modifying IAM/OIDC, an
agent-managed bootstrap role, static AWS credentials in GitHub.

## 18. Risks / open questions

1. **§0.1 must be resolved by explicit human decision** before an
   implementation plan can be written — this is the single biggest
   open item.
2. **§0.2's hypothesis** (near-empty permission set) should be treated
   as provisional until the actual discovery loop runs against real
   AWS.
3. **Batch 24 (`feat/batch24-demo-cli`) is unmerged** — Batch 25 does
   not depend on it structurally (§1's sequencing note), but the
   portfolio "story" (§15) reads oddly if the CLI that's supposed to
   produce these PRs doesn't exist on `main` yet. Worth a merge
   decision independent of Batch 25.
4. GitHub's exact AWS OIDC provider thumbprint/setup guidance should be
   re-verified at actual bootstrap-apply time (AWS/GitHub have changed
   this mechanism before; treat this document's own drafting date,
   2026-09-26, as authoritative here, not any earlier training-data
   assumption).
5. Action pinning (§12) — exact commit SHAs for
   `github/actions-oidc-debugger`, `aws-actions/configure-aws-credentials`,
   `hashicorp/setup-terraform` — is implementation-time work, not
   decided here.

## 19. Recommended implementation sequence (not an implementation plan)

1. Human decision on §0.1 (Option 1/2/3).
2. §5's temporary OIDC-debugger workflow → record real claims → delete
   it.
3. Bootstrap plane applied manually, outside this repository (§6).
4. `aws-plan` job added to `ci.yml`, gated per §11/§12, initially with
   only `sts:GetCallerIdentity` (§0.2's hypothesis) attached to
   `IaCPlanRole`.
5. Discovery loop (§8) against one real, authorized PR — add
   permissions one at a time only if genuinely needed.
6. Freeze the policy; add §13's structural regression tests and §14's
   policy-simulation negative-path check.
7. Record §15's acceptance evidence.

A full task-by-task implementation plan (mirroring Batch 23/24's own
planning documents) is the next artifact, written only after a human
has reviewed and responded to §0.1 and §18 specifically.

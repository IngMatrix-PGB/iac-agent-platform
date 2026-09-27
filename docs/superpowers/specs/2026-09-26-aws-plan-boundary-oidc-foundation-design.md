# Design Spec: AWS Plan Boundary / GitHub OIDC Foundation (Batch 25)

Status: **APPROVED WITH HUMAN DECISIONS RECORDED BELOW — design only,
implementation plan gate now OPEN (see §20).**
Discovery base: `origin/main` `460d717` (PR #4 Batch 23 + PR #5 Gate D demo
artifact, both merged). **`feat/batch24-demo-cli` merged to `main` via
PR #6 on 2026-09-26 (merge commit `0e92809`) — the last closure-gate
condition is now satisfied.**

## Human decisions (2026-09-26, recorded verbatim in substance)

1. **Real AWS provider boundary:** the CI-owned Terraform
   `_override.tf` approach (§0.1 Option 1) is **approved**. The
   production renderer (`terraform_render.py`) is **not** modified.
   Acceptance is strengthened: OIDC/STS assumption succeeding is
   **not** sufficient evidence on its own — the design must separately
   prove the AWS provider actually used the resulting credentials (see
   §0.1's updated acceptance split, A/B).
2. **IAM permission baseline:** do **not** pre-grant the candidate
   SQS/Lambda/DynamoDB/IAM read matrix (§7). Start from the empirical
   minimum (§0.2's hypothesis — likely just identity/provider-init
   operations) and add exactly one action at a time, only against
   observed `AccessDenied` evidence, each documented with why it's
   required and confirmed non-mutating. §7/§8 updated accordingly.
3. **Batch 24 prerequisite (hard gate):** Batch 25 implementation
   **must not begin** until `feat/batch24-demo-cli` has completed
   review, passed CI, and merged to `main`. The implementation branch
   must be cut from the `main` commit that contains Batch 24. This
   design document is approved; the **implementation plan is not
   written yet** because this gate is still open (§20).

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

**DECISION (2026-09-26): Option 1 is approved.** The generated
Terraform artifact and the production renderer
(`terraform_render.py`) are never modified. The opt-in `aws-plan` CI
job materializes an execution-only `*_override.tf` inside the
temporary Terraform workspace (never committed, never part of
`generated/<request_id>/`) that disables the `skip_*` provider flags
for that one execution context, so the AWS provider uses the real
OIDC/STS-derived credentials from the job environment. This is
execution-boundary configuration, not generated infrastructure — it
never becomes part of the PR's own diff.

**Acceptance is two-part, and part A alone is explicitly insufficient:**

- **A. GitHub OIDC successfully assumed `IaCPlanRole`** — provable via
  the CI log's own STS response / `aws sts get-caller-identity` echo
  (account/ARN only, never credential values).
- **B. Terraform's AWS provider actually used those credentials** —
  provable independently of A, e.g. by asserting the plan log shows
  the provider's own initialization step completed (not
  short-circuited by the skip-flags) and/or by a deliberate,
  non-destructive read the override enables (such as the provider's
  internal `GetCallerIdentity` call surfacing in the plan's debug
  log). A successful `AssumeRoleWithWebIdentity` call proves GitHub↔AWS
  trust works; it does **not** by itself prove Terraform ever touched
  AWS — those are two separate claims, and both must be evidenced.

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
- **B (OIDC trust, no hardcoded `sub`):** confirmed — see §5.
  **Correction (Task 11, empirically verified 2026-09-26):** the
  original assumption above was wrong. This repository's `created_at`
  is `2026-09-13T19:18:45Z` — *after*, not before, GitHub's
  2026-07-15 immutable-subject cutover — so it was never eligible for
  the legacy format. The observed, authoritative `sub` for a
  `pull_request` event is
  `repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request`
  (immutable `owner_id@repo_id` shape). This is now the only value the
  trust policy is written against — never the legacy shape.
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
- **New invariant surfaced by §0.1, now a locked decision:** *the
  generated Terraform artifact and `terraform_render.py` are never
  modified for this batch* — confirmed and locked, not merely
  provisional (see "Human decisions," item 1).
- **New invariant, locked:** the `IaCPlanRole` permission set is
  derived strictly from observed `AccessDenied` evidence, one action at
  a time — the candidate matrix in §7 is documentation of a rejected
  starting hypothesis, never a pre-grant (see "Human decisions," item
  2, and §7/§8 below).
- **New invariant, locked:** Batch 25 **implementation** does not begin
  until `feat/batch24-demo-cli` is merged to `main`, and the
  implementation branch is cut from the `main` commit containing it
  (see "Human decisions," item 3, and §20).

---

## 5. OIDC claim-discovery design

**Goal:** determine this repository's actual emitted `aud`/`sub`
before writing any AWS trust policy — never assume the legacy format.

**Status: executed (Task 11, 2026-09-26).** The plan originally
specified `github/actions-oidc-debugger`, but that action was found
**archived** (2025-09-22, read-only) before use and was **not**
depended on. Discovery instead used GitHub's own documented
`ACTIONS_ID_TOKEN_REQUEST_URL`/`ACTIONS_ID_TOKEN_REQUEST_TOKEN`
mechanism directly, in an inline Python step
(`shell: python3 {0}`), decoding the JWT payload locally and printing
only the non-secret claim subset — the raw token was never echoed,
logged, or persisted. Concretely, what was done:

1. Added a **temporary, throwaway** workflow (never the real
   `ci.yml`), `.github/workflows/oidc-claim-debugger.yml`, on a
   `pull_request` trigger from this exact repository, requesting
   `id-token: write` only in that one temporary job.
2. Captured only the **sanitized, decoded claim fields**
   (`aud`, `sub`, `repository`, `repository_owner`, `repository_id`,
   `repository_owner_id`, `event_name`, `ref`, `workflow_ref`,
   `job_workflow_ref`, `iss`) — never the encoded JWT string itself.
3. **Result:** `sub` is the **immutable**
   `repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request`
   shape, not the legacy `repo:IngMatrix-PGB/iac-agent-platform:pull_request`
   shape this design originally assumed (see the correction in §4,
   item B). Root cause: this repository's `created_at` is
   `2026-09-13T19:18:45Z`, after the 2026-07-15 cutover — it was never
   eligible for the legacy format.
4. Confirmed the run did **not** reference a GitHub Environment
   (`ci.yml` has no `environment:` key anywhere) — the observed `sub`
   ends in `:pull_request`, not `:environment:<name>`.
5. The temporary discovery workflow, its branch, and its throwaway PR
   (#7) are retired per the Task 11 closure runbook
   (`docs/aws-plan-boundary.md`) — the sanitized claim evidence above
   is preserved here and in that runbook instead of only existing in
   the (now-deleted) PR/run.

The recorded `job_workflow_ref` above belongs to this **temporary**
discovery workflow only — it must never be copied into the production
trust policy or into any `job_workflow_ref` restriction. The trust
policy (§6) is written from the recorded `sub` value only, restricted
to the `aud`/`sub` `StringEquals` condition — no workflow-pinning
condition is added unless a future, separately human-reviewed decision
explicitly adds it.

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

**DECISION (2026-09-26): none of the families below are pre-granted.**
The starting `IaCPlanRole` policy at implementation time contains
**only** `sts:GetCallerIdentity` (§0.2's empirical minimum). Everything
else in this table is a **rejected-as-pre-grant hypothesis**, kept here
only so the discovery loop (§8) has candidates to test *against*
observed `AccessDenied` evidence — not a list to grant upfront.

| Family | Hypothesis (not granted) | Status |
|---|---|---|
| STS | `sts:GetCallerIdentity` | **Starting grant** — provider init, needed once §0.1's override removes the skip-flags |
| SQS | `GetQueueAttributes`, `GetQueueUrl`, `ListQueueTags`, `ListQueues` | **Not granted.** Test empirically; per §0.2, likely unnecessary for a from-scratch, no-state plan |
| Lambda | `GetFunction`, `GetFunctionConfiguration`, `GetFunctionCodeSigningConfig`, `GetPolicy`, `ListTags`, `ListVersionsByFunction` | **Not granted.** Same caveat |
| DynamoDB | `DescribeTable`, `DescribeContinuousBackups`, `DescribeTimeToLive`, `ListTagsOfResource` | **Not granted.** Same caveat |
| IAM | `GetRole`, `GetRolePolicy`, `ListRolePolicies`, `ListAttachedRolePolicies` | **Not granted.** Same caveat; would only matter if the provider ever reads an *existing* execution role (not the case for a brand-new one) |

None of these are approved as a final policy. §8/§9 are authoritative
about what happens next.

---

## 8. Permissions requiring empirical discovery

**Locked process (human decision item 2):** implementation starts from
`sts:GetCallerIdentity` alone. For every subsequent `AccessDenied`
during a real `terraform plan` (with §0.1's override in place): (1)
identify the exact AWS API action denied, (2) confirm the AWS provider
genuinely requires it for this specific plan, (3) confirm it is
non-mutating, (4) add only that one action, with a written note of why,
(5) rerun. Never widen in bulk, never jump to
`AdministratorAccess`/`PowerUserAccess`/persistent `ReadOnlyAccess`.
§7's families are candidates to check against, in the order discovery
actually surfaces them — not a checklist to grant preemptively.

Expected outcome, stated as a hypothesis to be confirmed, not assumed:
the loop converges quickly (1–2 iterations) because there is no
existing state to refresh and no AWS-querying `data` source in the
current generated composition. If discovery instead reveals additional
calls (e.g., the AWS provider internally validating an ARN format
against a live IAM lookup, which is plausible but not confirmed), each
is added one at a time, per the loop above, with its justification
documented in the same commit that adds it.

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
| Compromised workflow dependency/action | `aws-actions/configure-aws-credentials`, `hashicorp/setup-terraform` should be pinned to a specific commit SHA (not a floating tag) in the eventual production `aws-plan` job — noted here as a requirement, not yet done. (`github/actions-oidc-debugger` is **not** a production dependency: it was found archived and was never used — Task 11's one-time discovery step used GitHub's own native token-request mechanism inline instead, with no third-party action to pin.) |
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

1. ~~§0.1 must be resolved by explicit human decision~~ — **resolved
   2026-09-26: Option 1 approved** (see "Human decisions," item 1).
2. **§0.2's hypothesis** (near-empty permission set) remains
   provisional until the actual discovery loop runs against real AWS —
   this is expected and correct; it is *why* §8 is a loop, not a
   one-shot grant (see "Human decisions," item 2, now locked as
   process).
3. ~~Batch 24 (`feat/batch24-demo-cli`) is unmerged~~ — **resolved
   2026-09-26: merged to `main` via PR #6, merge commit `0e92809`**
   (re-verified: `git cat-file -e origin/main:src/iac_agent/cli/main.py`
   succeeds). The implementation branch for Batch 25 must be cut from
   `0e92809` or later, not from the earlier `460d717` this design was
   drafted against.
4. GitHub's exact AWS OIDC provider thumbprint/setup guidance should be
   re-verified at actual bootstrap-apply time (AWS/GitHub have changed
   this mechanism before; treat this document's own drafting date,
   2026-09-26, as authoritative here, not any earlier training-data
   assumption).
5. Action pinning (§12) — exact commit SHAs for
   `aws-actions/configure-aws-credentials`,
   `hashicorp/setup-terraform` — is implementation-time work, not
   decided here. (`github/actions-oidc-debugger` was found archived
   during Task 11 and was not used — see §5.)

## 19. Recommended implementation sequence (not an implementation plan)

0. ~~Gate: merge `feat/batch24-demo-cli` to `main` first~~ — **done**
   (PR #6, `0e92809`). Cut the Batch 25 implementation branch from
   this commit or later.
1. ~~Human decision on §0.1~~ — done; Option 1 is locked.
2. §5's temporary OIDC-debugger workflow → record real claims → delete
   it.
3. Bootstrap plane applied manually, outside this repository (§6).
4. `aws-plan` job added to `ci.yml`, gated per §11/§12, initially with
   only `sts:GetCallerIdentity` attached to `IaCPlanRole` (§0.2/§8,
   locked as the starting grant — no pre-granted family from §7).
5. Discovery loop (§8) against one real, authorized PR — add
   permissions one at a time, each with a written justification, only
   against observed `AccessDenied`.
6. Freeze the policy; add §13's structural regression tests and §14's
   policy-simulation negative-path check.
7. Record §15's acceptance evidence, including both parts of §0.1's
   acceptance split (A: OIDC assumed; B: provider actually used the
   credentials).

## 20. Batch 25 closure gate (explicit, checked 2026-09-26)

| Gate condition | Status |
|---|---|
| §0.1 (real AWS provider boundary approach) decided | ✅ Option 1 approved |
| §7/§8 (IAM permission baseline approach) decided | ✅ empirical-minimum locked, no pre-grant |
| `feat/batch24-demo-cli` merged to `main` | ✅ merged 2026-09-26 via PR #6 (`0e92809`) |

**Batch 25 status: design APPROVED; implementation plan gate OPEN.**
All three closure conditions are satisfied. A task-by-task
implementation plan may now be written, cut from `main` at `0e92809`
or later — this still requires a separate, explicit human go-ahead to
begin (this document being closed is not itself that go-ahead).

## 21. Implementation status (updated 2026-09-26, post-Task 11 closure)

| Task(s) | Gate | Classification | Evidence |
|---|---|---|---|
| 1–9 | A (deterministic) | **COMPLETE** | 1381 unit tests passing (3 `xfail` by design, Task 13-gated); `ruff`/`terraform fmt`/`git diff --check` clean. No real network/AWS/GitHub call involved. |
| 10 | B (real tool, no credentials) | **COMPLETE** | Real `terraform fmt/init/validate/plan/show` against `bootstrap/aws-oidc/`, credential-free (fake `AWS_ACCESS_KEY_ID=test` + full skip-flags) — proves the module is syntactically/semantically valid Terraform, not that it authenticates against a real account. |
| 11 | C, part 1 (real GitHub OIDC) | **COMPLETE — real evidence** | Real workflow run (`36287435611`), real throwaway PR (#7, closed), real observed `aud`/`sub` — recorded in §5 above and in `docs/aws-plan-boundary.md`. This is genuine empirical evidence, not fabricated. |
| 12 | C, part 2 (real AWS apply) | **DEFERRED — authorized AWS sandbox required** | Blocked: the only AWS credentials available on this machine resolve to ClubHub corporate account `891377250201` (profiles `no-prod`, `iac-agent-lab`), explicitly excluded from this project's authority boundary by human decision (2026-09-26). No `terraform apply` has been run anywhere for this module. Per design invariant 1, this step is never performed by the agent regardless — it always requires a human, but that human also needs a personal/lab account, which does not yet exist. |
| 13 | C, part 3 (`aws-plan` job in `ci.yml`) | **DEFERRED** | Requires the real `IaCPlanRole` ARN from Task 12, which does not exist yet. Task 6's structural contract test remains intentionally `xfail(strict=True)` — un-`xfail`-ing it without Task 13 actually landing would be exactly the fabrication this closure must avoid. |
| 14 | D (empirical IAM discovery loop) | **DEFERRED** | Requires Task 13. The current permissions policy (`sts:GetCallerIdentity` only) is the *starting hypothesis* from §0.2/§8, not an empirically-confirmed final policy — it must not be described as "frozen" or "validated against real AWS" until this loop actually runs. |
| 15 | D closing (freeze policy + negative-path test) | **DEFERRED** | The design's own `iam:SimulatePrincipalPolicy` negative-path check (§14) is itself a real AWS API call against a real, applied role — it cannot be executed, faked, or pre-written as passing without Task 12–14 first being real. |
| 16 | E (video acceptance evidence) | **DEFERRED** | Depends on the full real positive-path story (Tasks 12–15), none of which exists yet. |

**Security invariants proven so far (structurally, Tasks 1–9, and confirmed unweakened by this closure pass):**
- `bootstrap/aws-oidc` is never referenced as a trusted module by `TerraformRunner`/`build_iac_workflow` (`tests/unit/bootstrap/test_no_self_management.py`).
- The generated-artifact renderer (`src/iac_agent/providers/aws/terraform_render.py`) and `generated/` output are untouched by Batch 25.
- `ci/aws_plan/provider_override.tf.template` is CI-owned, referenced by no `src/` code, and explicitly enables (not skips) real credential validation — proven by an offline merge-simulation test (Task 5), never a live plan.
- `TerraformRunner` has no `apply`/`destroy` method (unchanged since Batch 20-something; re-verified, not re-implemented, this batch).
- The bootstrap trust policy (`bootstrap/aws-oidc/main.tf`) sources `sub` only from `var.github_oidc_subject`, one `StringEquals` condition, no wildcard, no literal repo string ever hardcoded (`test_trust_policy_subject_is_a_variable_never_a_literal_repo_string`).
- No static AWS credentials, no remote Terraform backend, anywhere in this repository (Task 9's sweep, re-run clean this closure pass).

**Real-AWS evidence still missing (and not claimed to exist):**
- No real `terraform plan`/`apply` has ever succeeded against a real, non-fake AWS account for `bootstrap/aws-oidc`.
- No IAM OIDC provider or `IaCPlanRole` has been created in any AWS account.
- No real GitHub Actions run has ever assumed `IaCPlanRole` via STS.
- No empirical `AccessDenied`-driven permission has ever been added beyond the starting `sts:GetCallerIdentity` hypothesis.
- No `iam:SimulatePrincipalPolicy` negative-path proof exists.

**Conclusion:**

**BATCH 25 IMPLEMENTATION COMPLETE — REAL-AWS OIDC/PLAN ACCEPTANCE DEFERRED PENDING AUTHORIZED SANDBOX**

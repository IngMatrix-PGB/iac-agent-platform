# AWS Plan Boundary / GitHub OIDC Foundation — Implementation Plan (Batch 25)

**Spec:** `docs/superpowers/specs/2026-09-26-aws-plan-boundary-oidc-foundation-design.md`
(design commit `28b155d`, carried onto this plan's branch as `523e557`/`2397ca8`/`1969cce`).
**Baseline:** `main` `0e92809` (Batch 24 merged — `src/iac_agent/cli/` present).

**Goal:** deterministically prove a GitHub PR can obtain short-lived AWS
credentials via OIDC, assume a least-privilege `IaCPlanRole`, and run a
real Terraform plan — while the assumed identity structurally lacks
mutation authority. Not deployment.

## Branch/baseline integration note

The Batch 25 design was drafted on a branch cut before Batch 24 merged.
This plan's branch (`docs/batch25-aws-plan-boundary-plan`) was created
fresh from `main` `0e92809` and the three approved design-doc commits
were cherry-picked onto it — no contradiction, no obsolete baseline;
the design doc's path didn't exist on `main` at all, so the cherry-pick
was conflict-free. **All implementation branches for this plan must be
cut from this plan's own branch (or from `main` `0e92809`+), never from
the old, pre-Batch-24 design branch.**

## Global constraints (restated from the approved design, not reopened)

1. Separate control plane: `iac-agent-platform` never creates, modifies,
   or applies the GitHub OIDC provider or `IaCPlanRole`'s trust/permissions
   policy. A human applies bootstrap Terraform manually.
2. `pull_request` only, never `pull_request_target`.
3. Real AWS plan is opt-in (`aws-plan` label + authorized-actor check +
   head-repo-only + GitHub's "require approval" setting).
4. `id-token: write` only on the one AWS-plan job.
5. No static AWS keys in GitHub, ever.
6. `AssumeRoleWithWebIdentity`, short session.
7. OIDC claims verified empirically (§5 of the design) before the trust
   policy is frozen — never hardcode `sub` from assumption.
8. CI-owned `*_override.tf` is the only mechanism that changes real-AWS
   plan behavior. `src/iac_agent/providers/aws/terraform_render.py` and
   every `generated/<request_id>/` artifact are never modified.
9. IAM policy starts at `sts:GetCallerIdentity` only. Every other
   permission is added one at a time, only against an observed,
   justified, non-mutating `AccessDenied`. Never `AdministratorAccess`/
   `PowerUserAccess`/persistent `ReadOnlyAccess`. `iam:PassRole` never
   granted.
10. No remote Terraform state, no S3 backend, no state locking.
11. No `terraform apply`/`destroy` anywhere, ever.
12. Fakes/fixtures live only in test files or the dedicated `bootstrap/`
    directory — never inside `src/`.
13. Git discipline matches every prior batch: no `Co-Authored-By`
    trailer, `IngMatrix-PGB` identity, never force-push, never push
    without separate explicit instruction.

---

## Gate model

| Gate | Contents | Human authorization required? |
|---|---|---|
| **A — deterministic/offline** | Tasks 1–9: policy fixtures, structural tests, `_override.tf` template, workflow YAML structural tests, docs | No — auto-run |
| **B — bootstrap/tool validation** | Task 10: real Terraform `fmt/init/validate/plan` against the bootstrap module, still credential-free | No — auto-run (`real_tool`, same discipline as existing suite) |
| **C — real GitHub OIDC / AWS identity** | Task 11 (claim discovery), Task 12 (bootstrap manually applied by the human, outside this repo/session), Task 13 (`aws-plan` job added to `ci.yml`, run once to prove OIDC→STS assumption only) | **Yes — explicit, separate authorization** |
| **D — real AWS Terraform plan** | Task 14 (discovery loop against real AWS), Task 15 (freeze policy + regression tests) | **Yes — explicit, separate authorization, per discovery iteration** |
| **E — video/demo acceptance** | Task 16 | **Yes — explicit, separate authorization** |

No task in Gate A or B calls AWS, OpenAI, or performs a GitHub write
operation. Nothing in this plan is executed by writing it.

---

## File structure

| File | Responsibility |
|---|---|
| `bootstrap/aws-oidc/{main,variables,outputs,versions}.tf` | Bootstrap Terraform: OIDC provider + `IaCPlanRole` + trust policy + permissions policy. Human-applied only, never by `TerraformRunner`. |
| `bootstrap/aws-oidc/policy/iac_plan_role_permissions.json` | The frozen, empirically-derived permission document — starts as `sts:GetCallerIdentity` only. |
| `bootstrap/aws-oidc/README.md` | Operator runbook: how to apply, how to rotate, how to extend the policy per the discovery loop. |
| `ci/aws_plan/provider_override.tf.template` | The CI-owned override template (execution-boundary only, never generated workload Terraform). |
| `.github/workflows/ci.yml` | Modified: new `aws-plan` job (Task 13, human-gated Gate C). |
| `.github/workflows/oidc-claim-debugger.yml` | Temporary, deleted after Task 11's discovery run. |
| `docs/aws-plan-boundary.md` | Operator-facing documentation (mirrors `docs/ci.md`'s style). |
| `pyproject.toml` | New `real_aws_plan`/`real_bootstrap_tool` pytest markers. |
| `tests/integration/test_bootstrap_aws_oidc_terraform.py` | Real Terraform `fmt/init/validate/plan` against `bootstrap/aws-oidc/`, credential-free. |
| `tests/unit/bootstrap/test_iam_plan_role_policy.py` | Deterministic policy-document assertions. |
| `tests/unit/ci/test_aws_plan_workflow_structure.py` | Deterministic YAML-structure assertions on `ci.yml`. |
| `tests/unit/ci/test_provider_override_template.py` | Deterministic assertions on the override template's content and non-invasiveness. |
| `tests/integration/test_cli_real_aws_plan.py` | `real_aws_plan`-marked, human-gated — Tasks 14+. |

Do **not** modify: `src/iac_agent/providers/aws/terraform_render.py`,
anything under `generated/`, `TerraformRunner`'s method set, the
resolver, `IntentResolutionService`, the CLI.

---

### Task 1: `real_aws_plan` pytest marker

**Files:** `pyproject.toml`
**Objective:** register the marker exactly like `real_tool`/`real_llm` — classification only, no behavior change to default collection.
**Tests written first:** none (this is metadata) — instead, a one-line assertion in a new `tests/unit/test_pytest_markers.py` that `real_aws_plan` and `real_bootstrap_tool` appear in `pyproject.toml`'s `markers` list.
**RED evidence:** `pytest tests/unit/test_pytest_markers.py -v` fails (markers absent).
**Minimum implementation:** two new lines in `[tool.pytest.ini_options].markers`, worded like the existing two.
**GREEN evidence:** same test passes; `pytest -m "not real_tool and not real_llm and not real_aws_plan and not real_bootstrap_tool" -q` still collects and passes the full existing suite unchanged.
**Validation:** `pytest tests/unit/test_pytest_markers.py -v`; full deterministic suite.
**Commit boundary:** `test: register real_aws_plan and real_bootstrap_tool pytest markers`
**Security invariant:** none directly — enables every later gate to stay separately excluded from default CI, exactly like `real_tool`/`real_llm` already are.
**Deterministic/offline.**

---

### Task 2: Bootstrap Terraform — OIDC provider + `IaCPlanRole` skeleton

**Files:** `bootstrap/aws-oidc/{main,variables,outputs,versions}.tf`
**Objective:** hand-author the bootstrap module: `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`, `aws_iam_role.iac_plan_role` with a trust policy referencing a **variable** for `sub` (never hardcoded — Task 11 supplies the real value later), and a permissions policy resource that reads `policy/iac_plan_role_permissions.json` (Task 3) via `file()`/`templatefile()`.
**Tests written first:** `tests/unit/bootstrap/test_bootstrap_module_structure.py` — asserts (via `hcl2`/text-parsing, no `terraform` binary needed) that the module declares exactly one `aws_iam_openid_connect_provider`, exactly one `aws_iam_role`, that the role's `assume_role_policy` condition block references variables (not literal `IngMatrix-PGB/...` strings) for `sub`, and that no resource block anywhere in this directory is of a mutating, non-IAM-bootstrap type (defense against scope creep in this one module).
**RED evidence:** fails — directory/files don't exist.
**Minimum implementation:** the four `.tf` files, following this repo's existing module style (`terraform/modules/lambda/main.tf` as the closest precedent for trust-policy-document shape).
**GREEN evidence:** structure test passes.
**Validation:** `pytest tests/unit/bootstrap/test_bootstrap_module_structure.py -v`; `terraform fmt -check -recursive bootstrap/` (added to Quality job's existing `fmt` check scope in Task 13, not here).
**Commit:** `feat(bootstrap): add AWS OIDC provider and IaCPlanRole Terraform skeleton`
**Security invariant:** separate control plane (design invariant A) — this module is never referenced by `build_iac_workflow`'s `trusted_module_dirs`, never invoked by `TerraformRunner`.
**Deterministic/offline.**

---

### Task 3: Frozen permission document — empirical-minimum starting policy

**Files:** `bootstrap/aws-oidc/policy/iac_plan_role_permissions.json`
**Objective:** the actual IAM policy document, starting with **only**
`sts:GetCallerIdentity`, `Resource: "*"`, one statement.
**Tests written first:** `tests/unit/bootstrap/test_iam_plan_role_policy.py`:
- policy has exactly one statement family at this stage (`sts:GetCallerIdentity`)
- no action matches `Create*`/`Update*`/`Delete*`/`Put*`/`Attach*`
- `iam:PassRole` absent
- `sts:AssumeRole` absent (only `AssumeRoleWithWebIdentity` is used, and that's the *trust* policy, not this permissions policy)
- no `Resource: "*"` statement contains a mutating action (defense-in-depth even though none should exist yet)
**RED evidence:** file doesn't exist, test fails on load.
**Minimum implementation:** the JSON file, exactly as described.
**GREEN evidence:** all assertions pass.
**Validation:** `pytest tests/unit/bootstrap/test_iam_plan_role_policy.py -v`
**Commit:** `feat(bootstrap): add empirical-minimum IaCPlanRole permission document`
**Security invariant:** design invariant 9/12/14/15 (empirical-minimum, no forbidden actions, no PassRole).
**Deterministic/offline.**

---

### Task 4: CI-owned Terraform provider override template

**Files:** `ci/aws_plan/provider_override.tf.template`
**Objective:** the execution-boundary file (§0.1/§9 of the design) that, when copied into a `generated/<request_id>/` workspace at plan time *only* (never committed there), removes the `skip_*` flags so the AWS provider authenticates for real.
**Tests written first:** `tests/unit/ci/test_provider_override_template.py`:
- the template file exists and parses as valid HCL (text-level check for a `provider "aws"` block)
- it does **not** set `skip_credentials_validation`/`skip_requesting_account_id`/etc. (i.e., it's the *absence* of those flags achieving the override, via Terraform's own `_override.tf` merge semantics — same block name, no skip keys — meaning the merged result drops them)
- a source-grep assertion that `ci/aws_plan/` is never imported/referenced by anything under `src/iac_agent/`
**RED evidence:** file absent.
**Minimum implementation:** the template file.
**GREEN evidence:** tests pass.
**Validation:** `pytest tests/unit/ci/test_provider_override_template.py -v`
**Commit:** `feat(ci): add CI-owned Terraform provider override template for real AWS plan`
**Security invariant:** design invariant 8 (renderer/generated-artifact untouched); the override lives entirely outside `src/` and `generated/`.
**Deterministic/offline.**

---

### Task 5: Prove the override actually changes plan behavior (still credential-free)

**Files:** `tests/integration/test_provider_override_real_tool.py`
**Objective:** using the **actual, real** `generated/req-20260926T215226Z/` artifact already on `main` (read-only — never modified), copy it to a `tmp_path`, apply Task 4's override on top (simulating what the real CI job will do), and run a real, still-credential-free `terraform init/validate/plan` (same `_PLAN_ENV_OVERRIDES` placeholder trick as today) to prove: (a) the merged provider block genuinely lacks the `skip_*` flags after the override is applied (inspect `terraform show -json` or `terraform providers schema` output showing the resolved config), (b) the plan output for the *resource* set is unchanged (still `+10/~0/-0`) — the override only affects provider auth behavior, nothing else.
**RED evidence:** test fails (override doesn't exist yet before Task 4, or this task's own assertions fail before the override is proven to merge correctly).
**Minimum implementation:** none beyond the test itself — Task 4's template should already satisfy it; if it doesn't, fix the template (not the generated artifact).
**GREEN evidence:** test passes; `git diff generated/` shows zero changes (the read-only source artifact was never touched, only a `tmp_path` copy).
**Validation:** `pytest tests/integration/test_provider_override_real_tool.py -m real_tool -v`
**Commit:** `test(ci): prove the provider override changes AWS auth behavior without touching generated Terraform`
**Security invariant:** design invariant 8/11 (acceptance part B's foundation — proving the provider *would* authenticate, before any real credential exists).
**Deterministic/offline** (real Terraform binary, but zero AWS credentials — `real_tool`-marked, matches existing convention).

---

### Task 6: `aws-plan` GitHub Actions job — structural design only (not yet added to `ci.yml`)

**Files:** `tests/unit/ci/test_aws_plan_workflow_structure.py` (test-first; the actual `ci.yml` change is Task 13, human-gated)
**Objective:** write the **test suite** for the job's eventual YAML shape now, so Task 13's implementation is mechanically checked against a pre-agreed contract, without touching `.github/workflows/ci.yml` yet.
**Tests (will fail until Task 13):**
- a job named `aws-plan` exists in `ci.yml`
- its `permissions` block sets `id-token: write` — and no other job in the file sets `id-token` at all
- its `if:` condition references the `aws-plan` label AND a head-repo/base-repo equality check AND an actor allowlist (three independent substring/AST checks, not just "contains a condition")
- the workflow's top-level trigger is still exactly `pull_request`/`push` on `main` — `pull_request_target` appears nowhere in the file
- `needs: [quality]` is present on the `aws-plan` job (cheap-gate-first, per design §10)
**RED evidence:** fails today (job doesn't exist) — this is intentional; the task's own deliverable IS the failing test, committed deliberately red, to be turned green only in Task 13 under separate authorization.
**Minimum implementation:** none in this task.
**GREEN evidence:** N/A until Task 13.
**Validation:** `pytest tests/unit/ci/test_aws_plan_workflow_structure.py -v` (expected: FAIL, documented as expected-red in the commit message).
**Commit:** `test(ci): specify the aws-plan job contract ahead of implementation (expected RED)`
**Security invariant:** design invariants 2/3/4/5 (pre-committing the contract before the risky change exists, so Task 13 cannot silently drift from it).
**Deterministic/offline.**

---

### Task 7: OIDC claim-discovery runbook (documentation only)

**Files:** `docs/aws-plan-boundary.md` (new), referencing `docs/superpowers/specs/2026-09-26-aws-plan-boundary-oidc-foundation-design.md` §5
**Objective:** write the exact, step-by-step operator runbook for Task 11's actual discovery run: how to add the temporary `github/actions-oidc-debugger` workflow, what to record (sanitized claims only), how to delete it afterward, and how the recorded `sub` feeds Task 2's trust-policy variable.
**Tests:** `tests/unit/test_docs_reference_aws_plan_boundary.py` — a one-line structural check that `README.md` references the new doc (mirrors the existing pattern for every other `docs/*.md` file).
**RED evidence:** README doesn't reference it yet.
**Minimum implementation:** the runbook doc + one README sentence, following the exact existing list-of-docs paragraph pattern.
**GREEN evidence:** test passes.
**Validation:** `pytest tests/unit/test_docs_reference_aws_plan_boundary.py -v`
**Commit:** `docs: add AWS plan boundary operator runbook`
**Security invariant:** design invariant 7 (claims verified before freezing, documented procedure — never ad hoc).
**Deterministic/offline.**

---

### Task 8: `bootstrap/` operator README

**Files:** `bootstrap/aws-oidc/README.md`
**Objective:** exact apply instructions (`terraform init/plan/apply` run by a human, from their own machine or a separate bootstrap pipeline — never this repo's CI, never `TerraformRunner`), how to extend the permissions policy per the Task 14 discovery loop, and an explicit statement of ownership: this directory is reference source, not something `iac-agent-platform` ever applies itself.
**Tests:** folded into Task 2's structure test — add one assertion that `README.md` exists in `bootstrap/aws-oidc/` and contains the string "never applied by iac-agent-platform" (or equivalent, exact wording decided at implementation time).
**RED/GREEN/Validation/Commit:** same mechanics as Task 2, extended.
**Security invariant:** design invariant 1/2 (the agent never controls what constrains it — stated in writing, not just structurally).
**Deterministic/offline.**

---

### Task 9: Structural no-apply / no-destroy / no-self-management regression tests

**Files:** `tests/unit/bootstrap/test_no_self_management.py`
**Objective:** the final Gate-A structural proof, tying everything in Tasks 1–8 together:
- `TerraformRunner` still has no `apply`/`destroy` (extend Batch 24's existing assertion, don't duplicate it — import and reuse)
- no file under `src/iac_agent/` references `bootstrap/` or `ci/aws_plan/` by path
- `bootstrap/aws-oidc/` is absent from `build_iac_workflow`'s `_DEFAULT_TRUSTED_MODULE_DIRS` (AST/import-level check against the real dict, not a string grep)
- no file under `bootstrap/` or `ci/aws_plan/` contains `terraform apply`/`terraform destroy` as literal invocation text (same sanitization discipline as Batch 24's own no-apply test — exclude any explicitly-documented negation string if one exists)
**RED/GREEN:** fails until the above are all true (should already be true after Tasks 2–4; this task is the regression guard, not new functionality).
**Validation:** `pytest tests/unit/bootstrap/test_no_self_management.py -v`; full Gate A suite: `pytest -m "not real_tool and not real_llm and not real_aws_plan and not real_bootstrap_tool" -q`; `ruff check .`; `git diff --check`.
**Commit:** `test: prove iac-agent-platform never self-manages its own AWS authority boundary`
**Security invariant:** design invariant 1/2/16 (mutation authority absent by default, structurally guarded against regression).
**Deterministic/offline — this is Gate A's closing task.**

**GATE A checkpoint after Task 9:** run the full deterministic suite + ruff + `git diff --check`. All must pass before Task 10.

---

### Task 10: Real Terraform validation of the bootstrap module (Gate B)

**Files:** `tests/integration/test_bootstrap_aws_oidc_terraform.py`
**Objective:** prove the bootstrap module is genuinely valid, plannable Terraform — real `terraform fmt/init/validate/plan` against `bootstrap/aws-oidc/` — **still fully credential-free**, using the exact same `skip_*`-flag + placeholder-env-var technique this repo already uses everywhere else (new-resource plans need no real read, per design §0.2 — this applies equally to the bootstrap module's own OIDC-provider/role resources, which are also entirely new).
**Tests:** assert `plan` succeeds, assert the plan's resource-change set matches exactly (`aws_iam_openid_connect_provider` × 1, `aws_iam_role` × 1, `aws_iam_role_policy`/`aws_iam_role_policy_attachment` × 1), assert zero destroy actions.
**RED evidence:** fails if Tasks 2–3 have any HCL error (first real compiler-level check of those hand-authored files).
**GREEN evidence:** passes.
**Validation:** `pytest tests/integration/test_bootstrap_aws_oidc_terraform.py -m real_tool -v`
**Commit:** `test(bootstrap): prove the AWS OIDC/IaCPlanRole module plans correctly, credential-free`
**Security invariant:** design invariant 10/11 (no remote state — this plan is local/ephemeral just like every other one in this repo); no AWS mutation (`plan` only, and still credential-free at this stage).
**Deterministic/offline in effect (no real AWS credentials used), `real_tool`-marked because it needs the real binary.**

**GATE B checkpoint after Task 10.**

---

### Task 11: OIDC claim discovery (HUMAN-GATED — Gate C, part 1)

**Not executed by writing this plan.** Requires a separate explicit
"authorize Gate C" message.

**Objective:** add the temporary `.github/workflows/oidc-claim-debugger.yml`
(per `docs/aws-plan-boundary.md`'s runbook, Task 7), push it, open a
throwaway PR against this repo, observe the sanitized claims
(`aud`, `sub`, `repository`, `event_name`) in the debugger action's own
output, record them, then delete the workflow file and close the
throwaway PR.
**GitHub mutation:** yes — one temporary workflow file, one throwaway PR, later closed/deleted. This is real, disclosed GitHub write activity, gated separately from everything in Gate A/B.
**Output:** the confirmed real `sub` string, recorded (not the JWT) into Task 2's trust-policy variable value (still not applied — that's Task 12).
**Commit boundary:** none until the debugger workflow is deleted again (net-zero to the repo's tracked history, aside from the throwaway PR's own record on GitHub).

---

### Task 12: Bootstrap plane applied for real (HUMAN-GATED — Gate C, part 2)

**Not executed by writing this plan, and not executed by me at all —
this is explicitly the repository owner's own action, outside this
session's tooling**, per design invariant 1: `iac-agent-platform`
(and this assistant, acting within it) never applies its own
constraining authority boundary. The human runs
`terraform init/plan/apply` against `bootstrap/aws-oidc/` from their
own machine or a separate bootstrap CI, using Task 11's confirmed
`sub` value, and reports back the resulting `IaCPlanRole` ARN
(non-secret) for Task 13 to consume.

---

### Task 13: `aws-plan` job added to `ci.yml` (HUMAN-GATED — Gate C, part 3)

**Not executed by writing this plan.** Requires the ARN from Task 12
and separate explicit authorization.
**Files:** `.github/workflows/ci.yml` (modified)
**Objective:** turn Task 6's pre-committed, currently-failing test
green — add the `aws-plan` job exactly per that contract, referencing
the real `AWS_PLAN_ROLE_ARN` as a plain (non-secret) repository
variable.
**GREEN evidence:** `pytest tests/unit/ci/test_aws_plan_workflow_structure.py -v` now passes; a real PR with the `aws-plan` label (opened by an authorized actor, from a same-repo branch) shows the job successfully assuming the role (Task 13's own acceptance: part A of §0.1's acceptance split — OIDC→STS only, no Terraform plan yet in this task).
**Commit:** `feat(ci): add opt-in aws-plan job — OIDC to STS assumption only`
**Security invariant:** every design invariant 2–7 simultaneously — this is the single highest-risk task in the whole plan and must not be bundled with anything else.

---

### Task 14: Real AWS plan + empirical IAM discovery loop (HUMAN-GATED — Gate D)

**Not executed by writing this plan.** Requires separate explicit
authorization, **per iteration** (the loop itself, not just its start).
**Files:** `bootstrap/aws-oidc/policy/iac_plan_role_permissions.json`
(only file that changes, one action at a time), `tests/integration/test_cli_real_aws_plan.py` (new, `real_aws_plan`-marked)
**Objective:** with Task 13's job now assuming `IaCPlanRole` for real,
add the actual `terraform init/validate/plan` (via Task 4's override)
step to the job, run it against one real, authorized PR, and follow
the design's §8 loop exactly: observe `AccessDenied` → identify exact
action → confirm non-mutating and genuinely required → add one line to
the policy JSON → document why in the same commit → rerun. Never widen
in bulk.
**Acceptance (§0.1 part B):** the plan log shows the provider's own
init step completing (not short-circuited by skip-flags) — proof
Terraform actually used the OIDC/STS credentials, independent of Task
13's part-A proof that GitHub/AWS trust assumption alone succeeded.
**Commit boundary:** one commit per permission added, each with its own
justification in the message — never a bulk grant.
**Security invariant:** design invariants 9/12/13/14/15 — this task
*is* that process, executed for real.

---

### Task 15: Freeze the policy + regression tests (Gate D closing)

**Files:** extends Task 3's `tests/unit/bootstrap/test_iam_plan_role_policy.py`
with the final, frozen action list; adds the IAM policy-simulation
negative-path check from design §14 (`iam:SimulatePrincipalPolicy`
against a representative mutating action, asserting `implicitDeny`) as
a separately-marked, human-gated test (never run automatically).
**Validation:** full Gate A+B suite still green; the new simulation
test passes once run under Gate D authorization.
**Commit:** `test(bootstrap): freeze empirically-derived IaCPlanRole policy and add negative-path proof`
**Security invariant:** design invariant 9 (observed necessity, not an assumed checklist) — this is the closing proof that the process was followed.

---

### Task 16: Video-ready acceptance evidence (HUMAN-GATED — Gate E)

**Not executed by writing this plan.** Documentation/evidence-capture
only, per design §15 — no new code. Records the full positive-path
story (PR → label → OIDC → STS → real plan → Checkov → explicit
no-static-keys/no-apply/no-destroy/no-mutation-authority statement) for
the portfolio.

---

## Report

1. **Plan path:** `docs/superpowers/plans/2026-09-26-aws-plan-boundary-oidc-foundation.md`
2. **Planning branch/base commit:** `docs/batch25-aws-plan-boundary-plan`, cut from `main` `0e92809`, carrying the approved design via cherry-picked commits `523e557`/`2397ca8`/`1969cce`.
3. **Task count:** 16 (9 Gate A, 1 Gate B, 3 Gate C, 2 Gate D, 1 Gate E).
4. **Planned production/infrastructure/workflow files:** `bootstrap/aws-oidc/*.tf` + `policy/*.json` + `README.md`; `ci/aws_plan/provider_override.tf.template`; `.github/workflows/ci.yml` (Task 13 only); `.github/workflows/oidc-claim-debugger.yml` (temporary, Task 11 only); `docs/aws-plan-boundary.md`; `pyproject.toml` (markers only).
5. **Planned test files:** `tests/unit/test_pytest_markers.py`, `tests/unit/bootstrap/test_bootstrap_module_structure.py`, `tests/unit/bootstrap/test_iam_plan_role_policy.py`, `tests/unit/ci/test_provider_override_template.py`, `tests/integration/test_provider_override_real_tool.py`, `tests/unit/ci/test_aws_plan_workflow_structure.py`, `tests/unit/test_docs_reference_aws_plan_boundary.py`, `tests/unit/bootstrap/test_no_self_management.py`, `tests/integration/test_bootstrap_aws_oidc_terraform.py`, `tests/integration/test_cli_real_aws_plan.py`.
6. **Deterministic gates:** A (Tasks 1–9), B (Task 10).
7. **Human-gated real-AWS gates:** C (Tasks 11–13), D (Tasks 14–15), E (Task 16).
8. **Commit boundaries:** one per task, exactly as listed above; Task 14 is one commit *per permission added*, never bulk.
9. **Security invariants explicitly tested:** separate control plane (Tasks 2/9), `pull_request`-only/no `pull_request_target` (Task 6), `id-token` scoping (Task 6), no static AWS keys (Task 9), empirical-minimum IAM/no forbidden actions (Tasks 3/15), no self-management of the authority boundary (Task 9), renderer/generated-artifact untouched (Tasks 4/5/9), provider actually authenticates (Task 5's structural proof, Task 14's real proof).
10. **Deviations/contradictions found:** none new. The one open item from the design (§0.2's hypothesis about a near-empty permission set) is not a contradiction — it's exactly what Task 14 will confirm or refute empirically.
11. **Exact point human authorization becomes mandatory:** the boundary between Task 10 and Task 11 — everything through Task 10 (Gate A+B) is deterministic and auto-runnable; Task 11 is the first task that touches a real GitHub OIDC/workflow surface and requires a separate "authorize Gate C" message, exactly like Batch 24's Gate C/D.
12. **Recommended execution mode:** **inline**, sequential, same discipline as Batch 24 — each task is small and independently reviewable; subagent-driven execution would not meaningfully parallelize a strictly-ordered, security-sensitive sequence like this one, and this repo's own established practice (Batches 21–24) has been inline execution with a human checkpoint at every gate boundary.

Do not implement any task from this plan without further instruction.

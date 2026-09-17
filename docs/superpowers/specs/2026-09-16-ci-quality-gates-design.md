# Design Spec: CI Quality Gates & Main Protection Strategy (Batch 22, design-only)

Status: **DRAFT — awaiting human review**
Scope: **design only** — no `.github/workflows/*`, no implementation
plan, no repository setting changes, no branch protection, no
production/test/Terraform changes accompany this document.

## 0. Purpose and scope

Batches 1–21 built a fully deterministic pipeline and proved it
locally: a full offline pytest run, a real-tool run, `ruff`, and a
handful of manual clean-room/`git diff --check` steps, all run by hand
before every commit. Nothing runs automatically on GitHub today — zero
Actions workflows exist, `main` has no branch protection, and there are
no required status checks (verified directly via the GitHub API, §1.9).

This document designs a small, deterministic CI architecture that moves
the repository's own existing local quality gates into GitHub Actions,
and separately (but does not yet enable) a future main-protection
policy that references those gates. It is a design document only.

**Process note:** a `SuggestSkills` search for a "Superpowers"
brainstorming/design skill returned zero results — no such skill is
installed in this environment (consistent with every prior design
batch in this project). This document was produced by the equivalent
explicit process instead: read-only repository discovery (§1), an
approach comparison per open question (§2–§16), then this written
spec — reported accurately rather than silently substituted.

## 1. Read-only discovery: current repository state

Every claim below was verified directly against the repository or its
locally installed toolchain, not assumed.

### 1.1 `pyproject.toml` (verbatim, relevant sections)

```toml
[project]
requires-python = ">=3.12,<3.13"
dependencies = [
    "pydantic>=2.6,<3",
    "langgraph>=1.2.11,<2",
    "langgraph-checkpoint-sqlite>=3.1.1,<4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6",
]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "real_tool: exercises the real Terraform and/or Checkov binary (not a fake/mock) — classification only, does not affect default collection (Batch 16.5).",
    "real_llm: exercises a real natural-language-to-ArchitectureIntent model call (not a fake) — classification only, does not affect default collection; skipped whenever no provider is configured (Batch 21).",
]
```

There is exactly **one** extras group, `dev` — no `test`, `ci`, or
`lint` group exists. The only reproducible install command the
repository actually supports is `pip install -e ".[dev]"`.

`requires-python` is a single, narrow band (`>=3.12,<3.13`) — this
project has never claimed multi-version compatibility, and nothing in
the codebase (no `sys.version_info` branches, no `typing_extensions`
back-compat shims) suggests it needs to.

### 1.2 Terraform version evidence

Every trusted module's `versions.tf` declares only a **floor**:

```
terraform/modules/{s3,api_gateway,dynamodb,sqs,lambda}/versions.tf:
  required_version = ">= 1.5.0"
```

No `.terraform-version` file, no `tflint` config, no exact pin exists
anywhere in the repository. The one authoritative *exact* version is
empirical: the locally installed binary used to produce every piece of
real-tool evidence in this project's own docs is `Terraform v1.16.1`
(confirmed via `terraform version`, and independently corroborated by
`docs/terraform-credential-free-plan.md`'s own recorded evidence:
`Terraform version: 1.16.1`, `AWS provider resolved: hashicorp/aws
v6.64.0` against the modules' `~> 6.0` constraint).

### 1.3 Checkov version evidence

Checkov is a `pip`-installed CLI tool, not a repository dependency (not
in `pyproject.toml` at all — it is assumed present on `PATH`, exactly
like `terraform`). Every empirically-derived expected-findings count in
`src/iac_agent/security/checkov_profiles.py` and
`composition_checkov_profiles.py` is explicitly commented "Verified
empirically (2026-09, Checkov 3.3.13, real scan of the …)". The locally
installed binary is confirmed as exactly `3.3.13` (`checkov --version`).

**This is load-bearing, not incidental**: Checkov's own built-in
ruleset changes between versions (new checks appear, existing checks
are sometimes retired or renumbered). If CI silently floated to
whatever `pip install checkov` resolves to on a given day, a Checkov
release could change `failed_checks`/finding counts the moment CI
starts installing it, with zero code change on this project's side —
indistinguishable from a real regression. **Checkov must be pinned to
exactly `3.3.13` in CI** (`pip install checkov==3.3.13`), not floated.

### 1.4 Test markers and default collection behavior (verified, not assumed)

Both markers' docstrings say "does not affect default collection" —
verified directly rather than trusted on faith:

```
$ pytest -q                              → 1284 collected (1283 passed, 1 skipped)
$ pytest -m real_tool -q                 → 63 passed, 1221 deselected
$ pytest -m real_llm -q                  → 1 skipped, 1283 deselected
$ pytest -m "not real_tool and not real_llm" -q
                                          → 1220 passed, 64 deselected, runtime 4.46s
```

So: a bare `pytest` **does** attempt to run `real_tool` tests (they are
never excluded by default — only individually `skipif`-guarded, see
§1.5), and `real_llm`'s one test always skips on its own regardless of
markers (it has its own `skipif` gate, see §1.6). The one command that
*explicitly and unconditionally* represents "the deterministic,
credential-free, network-free suite" — independent of whichever
binaries happen to be on a given machine's `PATH` — is:

```
pytest -m "not real_tool and not real_llm"
```

### 1.5 What the 63 `real_tool` tests actually require

All 30 files carrying `@pytest.mark.real_tool` were inspected. **Every
one of them** also carries:

```python
pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)
```

(verified by grep across all 30 files — zero unguarded). This means:
on a runner with neither binary installed, the entire `real_tool` suite
skips cleanly (reported as `skipped`, never `error`/`failed`) — it is
safe to run the bare `pytest -q` command anywhere, on any runner, with
or without Terraform/Checkov present.

What they actually exercise, once the binaries are present:
- Real `terraform fmt`/`init -backend=false`/`validate`/`plan`/`show
  -json` subprocess calls against every trusted module and the
  `serverless_worker`/`api_lambda` compositions.
- Real `checkov` scans against the rendered HCL.
- **Network requirement:** `terraform init` downloads the
  `hashicorp/aws` provider plugin (~hundreds of MB) from the public
  Terraform Registry over HTTPS — a real network dependency, but not a
  *credential*. GitHub-hosted runners have outbound internet access by
  default; nothing exotic is required.
- **Credential requirement:** none, by design. Every plan-touching test
  uses the exact `terraform_plan_env_overrides` fixture
  (`tests/integration/conftest.py`): `AWS_ACCESS_KEY_ID=test`,
  `AWS_SECRET_ACCESS_KEY=test` — placeholder strings, never real
  secrets — combined with every root test fixture's
  `skip_credentials_validation = true` /
  `skip_requesting_account_id = true` provider block. This is not new
  for Batch 22: it is the exact mechanism `docs/terraform-credential-
  free-plan.md` already documents and empirically verified (Batch 3):
  `terraform plan` never contacts a real AWS API, confirmed by
  observation, not merely by intent.
- **Runtime cost:** dominant. `pytest -m real_tool -q` measured
  **1575–1622 seconds (~26–27 minutes)** across three independent local
  runs (two on this machine, one on a freshly-provisioned worktree with
  no pre-warmed provider cache) — versus **4.46 seconds** for the
  entire deterministic suite (§1.4). The real-tool suite is
  essentially 100% of this project's current test wall-clock cost.
- **GitHub source-control:** zero real_tool test ever contacts
  `api.github.com`. `test_application_composition.py` (the one
  real_tool test touching source control) injects a fake
  `HttpTransport` (`QueueGitHubTransport`) — confirmed by reading the
  file. A second file,
  `tests/integration/test_sqs_workflow_source_control.py`, exercises
  the *real* `GitHubSourceControl` adapter class end-to-end but is
  **not** `real_tool`-marked and states its own hard rule in its module
  docstring: "zero real network access, zero contact with
  api.github.com" (Batch 14) — verified by grep, no
  `requests`/`urllib`/live-HTTP import anywhere in that file.

### 1.6 The `real_llm` marker (Batch 21, unchanged)

`tests/integration/test_architecture_intent_nl_real_model_eval.py`
contains exactly one function, `@pytest.mark.real_llm`, additionally
gated by `@pytest.mark.skipif(os.environ.get("IAC_AGENT_LLM_PROVIDER")
is None, ...)`, whose body **unconditionally** calls `pytest.skip(...)`
regardless of that env var — belt-and-suspenders, zero real model calls
possible under any CI configuration. No API key of any kind is read by
any production code. This batch does not touch this file or its
guarantee; CI must never set `IAC_AGENT_LLM_PROVIDER`, and no workflow
in this design does.

### 1.7 Offline golden evals: already inside the ordinary suite

Every deterministic golden-eval integration test
(`test_sqs_golden_evals.py`, `test_s3_golden_evals.py`,
`test_dynamodb_golden_evals.py`, `test_lambda_golden_evals.py`,
`test_api_lambda_golden_evals.py`, `test_serverless_worker_golden_evals.py`,
`test_architecture_intent_golden_evals.py`) carries **no** `real_tool`
marker — confirmed by grep (`grep -L "pytest.mark.real_tool"` over
every `*golden_evals.py` file returns all seven). They are plain
`tests/integration/*.py` files, collected and run by the ordinary
`pytest` invocation, and are therefore already inside the 1220 tests
the §1.4 required command runs. The *separate*, `real_tool`-marked
`*_golden_real_tool_eval.py` files are a different, additional
credential-free-but-binary-dependent real-Terraform/Checkov cross-check
of one representative scenario per resource — correctly excluded from
the same command, since they need the real binaries.

**Conclusion: offline evals need no separate CI command or job.**
Running them again in a second job would re-execute the same 1220 tests
a second time for no new signal — the exact anti-pattern this design is
asked to avoid — while still leaving eval regressions fully caught,
since they already fail the one required `pytest` invocation like any
other test.

### 1.8 `terraform fmt -check` viability (verified, not assumed)

```
$ terraform fmt -check -recursive -diff terraform/ tests/terraform/
$ echo $?
0
```

Passes cleanly today, needs no `terraform init` (no provider download,
no network, no credentials — `fmt` is pure syntax formatting against
the HCL parser bundled in the `terraform` binary itself), and costs
well under a second. This is a legitimate, cheap, deterministic static
check with no downside to including.

### 1.9 Current GitHub-side state (verified via `gh api`)

- `gh api repos/IngMatrix-PGB/iac-agent-platform/actions/workflows` →
  `{"total_count": 0, "workflows": []}` — zero workflows configured.
- `gh api repos/IngMatrix-PGB/iac-agent-platform/branches/main/protection` →
  HTTP 404 "Branch not protected" — no protection rule, no required
  status checks, on `main` today.
- Sole collaborator/maintainer: `IngMatrix-PGB` (this repository has no
  second human account with write access).

## 2. Job structure: comparison

| # | Structure | Runtime shape | Diagnostics | Maintenance | Verdict |
|---|---|---|---|---|---|
| 1 | One monolithic job (lint + offline tests + tool validation, sequential) | Every PR pays the ~27-minute real-tool cost, every time, even for a one-line docstring change | A single failure gives no signal about *which* of three very different concerns broke without reading the log | Simplest YAML, but a single ~27-minute required check is a poor day-to-day feedback loop | **Rejected** — makes the fast, deterministic 4.46s signal wait behind the slowest, most externally-dependent one for no reason |
| 2 | Separate jobs: `quality`, `tests`, `tool-validation` (parallel, independent) | The two *required* jobs (`quality`, `tests`) both finish in well under a minute; `tool-validation` runs in parallel and reports independently, never blocking the fast feedback | A failure's job name immediately says whether it was lint/format, deterministic test/eval behavior, or real Terraform/Checkov integration | Three small jobs in one workflow file — one place to look, `needs:` not required since nothing depends on anything else | **Recommended** |
| 3 | Highly fragmented (e.g. one job per resource type, one job per marker combination) | Marginal parallelism gain over #2, since `pytest` itself is already fast for the required path and the slow path (`real_tool`) doesn't benefit from resource-level splitting (it is already one coherent suite, not resource-isolated infra) | More check names to scroll through for no additional information — a `real_tool` failure in the S3 golden-eval-with-real-tool test is just as diagnosable from one `tool-validation` job's log as from ten | Ten+ check names is more branch-protection surface to keep in sync, more YAML to maintain, more UI noise for a solo maintainer | **Rejected** — no evidence-backed benefit over #2, real maintenance cost |

**Recommendation: Option 2** — one workflow file, three jobs.

## 3. `real_tool`: required, separate-optional, or excluded — comparison

| # | Approach | For | Against |
|---|---|---|---|
| A | Excluded from CI entirely | Zero CI cost; zero external dependency in CI | Loses the one signal that catches real Terraform/provider/Checkov drift (e.g. a provider schema change, or — per §1.3 — Checkov itself changing its ruleset) before a human notices manually; this signal has real value even if not required |
| B | Separate, non-required job/workflow | Keeps the real-tool signal visible on every PR (so a maintainer *can* look at it) without making a ~27-minute, network-and-toolchain-dependent job a merge blocker; failures here are informative, not gating | A PR can still merge while this job is red — requires the maintainer to actually look, rather than being enforced |
| C | Required CI gate | Strongest enforcement in principle | Directly contradicted by repository evidence (§1.5): ~27 minutes vs. 4.46 seconds for equivalent-or-better coverage of the same logic through fakes; a hard external dependency (public Terraform Registry availability, provider download reliability) in the *required* path, for signal that is already redundantly provided (renderer/policy/security-gate correctness is proven byte-for-byte through the deterministic suite; `real_tool` additionally proves the *real* Terraform/Checkov binaries agree, which is valuable but is a toolchain-integration concern, not a merge-blocking correctness concern) |

**Recommendation: B — `real_tool` as a separate, non-required job.**
Not chosen "because it currently passes" — chosen because the runtime
delta is two orders of magnitude, the correctness signal it adds beyond
the deterministic suite is toolchain-drift detection (valuable to see,
not something that should block a docs-only PR from merging), and it
introduces the project's only network dependency into what would
otherwise be an entirely offline, deterministic required path.

## 4. Python version strategy

**One version: 3.12** (the exact floor-and-ceiling `requires-python`
constraint already declares). No matrix. Nothing in this project has
ever depended on multi-version Python compatibility, and introducing
one now would triple every job's runtime for zero demonstrated benefit
— directly against the instruction not to add a matrix without
evidence. If the `requires-python` constraint is ever widened, this
decision should be revisited then, not anticipated now.

## 5. Terraform version strategy

**Pin exactly `1.16.1`** in the `tool-validation` job only (the
`quality` job's `terraform fmt -check` also needs a `terraform` binary
present — same pin, reused). This is the version every piece of
empirical evidence in this repository (`docs/terraform-credential-free-
plan.md`, this design's own §1.2 measurement) was produced against, and
it satisfies every module's `>= 1.5.0` floor. Never `latest` — a
silent Terraform upgrade could change `plan` output shape, HCL
formatting rules, or provider-resolution behavior with no corresponding
code change, exactly the same class of problem as an unpinned Checkov
(§1.3).

## 6. Checkov version strategy

**Pin exactly `3.3.13`** via `pip install checkov==3.3.13` in the
`tool-validation` job. See §1.3 — this is not a style preference, it is
required to keep the empirically-derived expected-findings counts in
`checkov_profiles.py`/`composition_checkov_profiles.py` meaningful. A
future, deliberate Checkov version bump is a real, reviewable change
(re-run the empirical verification, update the profile comments, update
this one CI pin) — not something that should happen silently because
`pip install checkov` resolved to a newer release on a given day.

## 7. Credential and network analysis

No environment variable shaped like `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, any `AWS_ROLE_ARN`/OIDC
configuration, or `IAC_AGENT_LLM_PROVIDER` is set by any workflow in
this design. The `quality` and `tests` jobs need no credentials and no
network beyond the standard `pip install` step (PyPI). The
`tool-validation` job needs outbound network access to the public
Terraform Registry (provider download) and PyPI (Checkov install) —
network, not credentials — plus the same placeholder
`AWS_ACCESS_KEY_ID=test`/`AWS_SECRET_ACCESS_KEY=test` pair the local
test fixtures already use, which (§1.5, §1.8, and the pre-existing
`docs/terraform-credential-free-plan.md`) is empirically proven to
never reach a real AWS API. **No repository evidence contradicts the
"no cloud credentials in required CI" requirement — no STOP condition
triggered here.**

## 8. Apply/destroy and GitHub-mutation verification

`grep -rn "terraform (apply|destroy)"` over `src/`, `tests/`, `evals/`
finds no functional invocation anywhere in this codebase (the only
historical hit, from Batch 21's own case-6 prompt-injection eval
fixture, is a JSON string literal proving the phrase has no execution
path — not a real call). No workflow in this design runs `terraform
apply` or `terraform destroy`, and no trusted module or test fixture
contains either. Every GitHub-source-control-touching test uses a fake
`HttpTransport` (§1.5) — CI can run every test in this repository
without ever mutating the real `IngMatrix-PGB/iac-agent-platform`
repository, another repository, or any AWS account.

## 9. Clean-room / safety checks suitable for CI

The project's own manual, ad hoc "clean-room grep" (used by hand at the
end of every prior batch) is exactly the kind of fragile, high-false-
positive-rate check this task warns against automating naively — it
already produces expected hits on its own rule text and on Batch 21's
deliberate prompt-injection fixture string. **Recommendation: do not
add a bespoke clean-room grep step to CI this batch.** The two existing,
purpose-built, low-false-positive mechanisms already do this job far
more precisely and are already part of the required `tests` job:

- `tests/unit/intent/test_trust_boundary_isolation.py` — `ast`-based
  (not substring) proof that `iac_agent.intent` never imports
  `iac_agent.execution`/`security`/`git`/`langgraph`. Zero false
  positives from docstring mentions (this was a real bug I hit and
  fixed during Batch 21 implementation with a naive substring version —
  documented here so it is not silently reintroduced).
- `tests/unit/intent/test_non_authoritative_metadata.py`'s
  `test_resolver_source_contains_no_confidence_attribute_reference` —
  a targeted, single-purpose source-text check for one specific
  invariant, not a broad keyword sweep.

A generic "no secrets" scan (e.g. a hypothetical `git diff | grep -iE
"AKIA|BEGIN.*PRIVATE KEY"` step) would be a reasonable, genuinely
low-false-positive addition, but is a **non-goal for this batch** — no
such incident or requirement exists in this repository's history, and
adding one without a demonstrated need repeats the "bureaucracy for its
own sake" pattern this design is explicitly asked to avoid elsewhere.

## 10. CI security: permissions

```yaml
permissions:
  contents: read
```

at the workflow level (inherited by all three jobs — none of them
override it). Nothing in any of the three jobs pushes a commit, writes
a PR comment, publishes a package, mutates Actions state, or requests
an OIDC token — no job needs `contents: write`, `pull-requests: write`,
`id-token: write`, or `actions: write`. There is no deployment step
anywhere in this design (a hard non-goal, §16 of the task, honored).

## 11. Triggers

```yaml
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
```

`pull_request` is the primary gate. `push` to `main` re-runs the same
checks post-merge as a cheap confirmation that the merged state (which,
per Batch 21's own reconciliation, is not always guaranteed to be
identical to what the PR showed — e.g. a non-fast-forward merge commit)
is still green; it never blocks anything since the merge has already
happened. **No `schedule:` trigger** — nothing in this repository
changes on a timer, and a scheduled real-tool run would just add
recurring runner minutes and Terraform-Registry/PyPI load for no
requesting event, contradicted by no evidence of need.

## 12. Concurrency

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

One in-flight run per ref (a PR branch, or `main`): pushing a new commit
to an open PR cancels that PR's still-running previous check instead of
letting two runs race to completion. Standard, low-risk, saves runner
minutes — recommended without qualification.

## 13. Caching

- **Python dependencies:** `actions/setup-python`'s built-in
  `cache: 'pip'` (keyed automatically off `pyproject.toml`) in `quality`
  and `tests` — a one-line addition, and this project's dependency set
  is small (`pydantic`, `langgraph`, `langgraph-checkpoint-sqlite`,
  `pytest`, `ruff`), so the win is modest but free.
- **Terraform provider plugin cache** (`tool-validation` only): the
  project's own `tests/integration/conftest.py` already documents the
  exact problem this solves locally (each independent `terraform init`
  re-downloading the same ~hundreds-of-MB `hashicorp/aws` provider) and
  already has a session-scoped `TF_PLUGIN_CACHE_DIR` fixture for local
  runs. In CI, caching that same directory keyed on
  `hashicorp/aws` + the pinned Terraform version (via `actions/cache`,
  keyed on a hash of the modules' `versions.tf`/lock file content plus
  the pinned version string) is a direct, evidence-backed win against
  the dominant cost identified in §1.5 — but it is explicitly a
  **non-required** job's optimization: a cache miss must still produce
  the exact same passing result, just slower, never a different one.
  **No shared cache is proposed for generated Terraform *workspaces***
  (`tfplan`, `.terraform.lock.hcl` per test run) — those are
  intentionally test-isolated today (per-test `tmp_path`) and nothing
  in this design changes that.

## 14. Stable check names

Status-check names become an implicit API the moment branch protection
references them (Phase B). Chosen for semantic stability, not tied to
tool versions or file names that may change:

| Job (YAML `name:`) | What it runs | Required (Phase B) |
|---|---|---|
| `Quality` | `ruff check .` + `terraform fmt -check -recursive` | **Yes** |
| `Tests` | `pytest -m "not real_tool and not real_llm"` (includes every offline golden eval) | **Yes** |
| `Tool Validation` | `pytest -m real_tool` (real Terraform 1.16.1 + Checkov 3.3.13) | **No** |

(GitHub's default displayed check name is `<workflow name> / <job
name>` — e.g. `CI / Quality` if the workflow itself is named `CI`. The
workflow name is proposed as `CI` for exactly this reason: short,
stable, unlikely to ever need renaming.)

## 15. Failure diagnostics

The three-job split (§2, §14) directly answers this: a red `Quality`
check means a lint/format problem; a red `Tests` check means a real
behavioral or eval regression in deterministic code; a red `Tool
Validation` check means the real Terraform/Checkov toolchain disagreed
with something (a provider update, a Checkov ruleset change, or a
genuine renderer bug) — informative on its own, and never conflated
with the other two categories in one opaque log.

## 16. Cost/runtime assessment

| Job | Expected wall-clock | Dominant cost |
|---|---|---|
| `Quality` | a few seconds | `ruff`/`terraform fmt` are near-instant; only `pip install -e ".[dev]"` (small dependency set) takes measurable time |
| `Tests` | ~5–15 seconds of test execution (measured locally: 4.46s) plus environment setup (`checkout`, `setup-python`, `pip install`) — realistically **under one minute** end-to-end on a hosted runner | environment setup, not the tests themselves |
| `Tool Validation` | **~25–30 minutes**, measured directly (three independent local runs: 1575s, 1622s, 1592s) | `terraform init`'s AWS provider download, repeated per test unless the plugin cache (§13) is warm; real Checkov scans are comparatively cheap |

No obvious duplicate execution exists in this design (§1.7 explicitly
rules out a redundant eval job). The one clear, evidence-backed
optimization opportunity is the provider plugin cache for `Tool
Validation` (§13) — proposed, not required, and explicitly non-blocking
if it misses.

## 17. Branch protection design (Phase B — proposed, NOT enabled this batch)

| Setting | Proposed value | Rationale |
|---|---|---|
| Require a pull request before merging | **Yes** | Keeps a PR/diff record and CI run for every change to `main`, even for a sole maintainer — cheap, and this project's own git history (Batch 21) already treats PRs as the unit of review |
| Required status checks | `Quality`, `Tests` (not `Tool Validation` — see §3) | Matches §14 exactly |
| Require branches to be up to date before merging | **Yes** | Low PR volume, low cost to require; prevents a stale-base merge from skipping a check that would have caught a conflicting change |
| Require conversation resolution before merging | Optional, not proposed as required this batch | No evidence of a need; can be added later with zero migration cost |
| Restrict who can push to matching branches / force-push protection | **Yes — block force-pushes to `main`** | Cheap, prevents an accidental history rewrite; this project's own working discipline (every batch this session) already treats force-push as something to avoid, this just enforces it structurally |
| Branch deletion protection | **Yes** | Trivially cheap, prevents an accidental `main` deletion |
| Required approving reviews | **No — explicitly not proposed** | `IngMatrix-PGB` is the sole collaborator with write access (§1.9). Requiring "N approvals from someone other than the author" on a single-maintainer repository is not enforceable without either a second human account or an admin bypass on every single PR — the classic "enterprise theater" anti-pattern this task explicitly warns against. If a second maintainer is ever added, this specific setting is the one to revisit, not before. |

**Phase A and Phase B are deliberately decoupled**: this batch's future
implementation plan (not written yet) would only add the three-job
workflow (Phase A) and let it run, unenforced, on real PRs first — branch
protection (Phase B) is a separate, later, explicitly human-approved
step, so that a workflow bug can never accidentally lock the sole
maintainer out of merging their own repository.

## 18. Non-goals (restated, unchanged from the task)

Deployment CI/CD, `terraform apply` automation, AWS authentication/OIDC
setup, release automation, package publishing, Docker publishing,
semantic-version automation, Dependabot, CodeQL, real LLM evaluation or
provider integration, UI deployment, and branch-protection *activation*
are all explicitly out of scope for Batch 22 and are not designed here
beyond the brief mentions above (§17) needed to keep Phase A/B
separation legible.

## 19. Explicit answers to every required design question

1. **Workflow files:** 1 (`.github/workflows/ci.yml`, name: `CI`) — not created this batch.
2. **Jobs:** 3 — `Quality`, `Tests`, `Tool Validation`.
3. **Required jobs (Phase B, future):** `Quality`, `Tests`.
4. **Does `real_tool` run in CI?** Yes, in the non-required `Tool Validation` job, on every trigger.
5. **Is `real_tool` required?** No (§3, Option B).
6. **Does `real_llm` run in CI?** No — always skips by its own double guard (§1.6); no workflow sets `IAC_AGENT_LLM_PROVIDER`.
7. **Python version:** 3.12 only, no matrix (§4).
8. **Terraform version:** pinned exactly `1.16.1` (§5).
9. **Checkov version:** pinned exactly `3.3.13` (§6).
10. **Exact install command:** `pip install -e ".[dev]"`.
11. **Exact Ruff command:** `ruff check .`.
12. **Exact pytest command(s):** `pytest -m "not real_tool and not real_llm"` (required, `Tests`); `pytest -m real_tool` (non-required, `Tool Validation`; skips cleanly if binaries are somehow absent, though `Tool Validation` explicitly installs them).
13. **Direct `terraform fmt` check?** Yes — `terraform fmt -check -recursive` over `terraform/` and `tests/terraform/`, folded into `Quality` (§1.8, §2).
14. **Eval execution strategy:** (A) already transitively exercised by the ordinary `Tests` command — no separate command or job (§1.7).
15. **Required permissions:** `contents: read` only, workflow-level (§10).
16. **Trigger strategy:** `pull_request` (to `main`) + `push` (to `main`); no schedule (§11).
17. **Concurrency strategy:** one run per `github.ref`, `cancel-in-progress: true` (§12).
18. **Cache strategy:** `setup-python`'s built-in pip cache for `Quality`/`Tests`; an optional, non-required Terraform provider-plugin cache for `Tool Validation` only, never affecting correctness (§13).
19. **Stable check names:** `Quality`, `Tests`, `Tool Validation` (§14).
20. **Future branch-protection settings:** §17 table, not enabled this batch.

## 20. Self-review checklist

- [x] All three approaches compared for job structure (§2) and for
      `real_tool` placement (§3), with an explicit, evidence-based
      recommendation for each — never "because it currently passes."
- [x] Every command in this document (`pytest` variants, `ruff check .`,
      `terraform fmt -check -recursive`) was actually run against this
      repository before being written down (§1.4, §1.8), with exact
      output/timing recorded, not assumed.
- [x] Marker behavior verified empirically (§1.4), not inferred from
      docstring text alone.
- [x] External binary requirements for every one of the 30 `real_tool`
      files enumerated and confirmed uniformly guarded (§1.5).
- [x] No credential of any kind (`AWS_*`, LLM provider) required by any
      proposed required job; explicitly checked against contradiction
      and none found (§7) — no STOP triggered.
- [x] No network-dependent test accidentally lands in the required
      path: `Tests` needs only PyPI (dependency install, already true
      of any Python CI); `Tool Validation` (the only job needing the
      public Terraform Registry) is explicitly non-required.
- [x] Eval coverage confirmed present in the required path without a
      duplicate, second expensive run (§1.7, §19.14).
- [x] Least-privilege permissions specified and justified (§10) — no
      write/OIDC/actions scope granted anywhere.
- [x] Check names chosen for semantic stability, independent of tool
      version strings or file names (§14).
- [x] Branch-protection design (Phase B) kept fully separate from
      workflow deployment (Phase A) — explicitly not enabled, with the
      reason stated (§17).
- [x] No implementation occurred: no file under `.github/` was created,
      no repository setting was changed, no branch protection was
      enabled.
- [x] No workflow YAML exists anywhere in this repository as of this
      commit (verified: `find .github -type f` returns nothing).
- [x] Only this one design document was created or modified by this
      batch.

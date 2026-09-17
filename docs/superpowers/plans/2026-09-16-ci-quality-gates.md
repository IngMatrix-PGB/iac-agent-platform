# CI Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic GitHub Actions quality gates for pull
requests and `main` without cloud credentials, paid APIs, deployments,
or AWS mutation.

**Architecture:** One GitHub Actions workflow named `CI` with three
stable jobs: `Quality`, `Tests`, and `Tool Validation`. `Quality` and
`Tests` are designed to become required checks only after successful
remote validation; `Tool Validation` remains non-required because it is
network-dependent and takes approximately 26–27 minutes.

**Tech Stack:** GitHub Actions, Python 3.12, pytest, Ruff, Terraform
1.16.1, Checkov 3.3.13.

**Spec:** docs/superpowers/specs/2026-09-16-ci-quality-gates-design.md

## Global Constraints

Carried forward verbatim from the approved design — none of these are
open for reinterpretation during implementation:

1. **One workflow, three jobs, fixed names.** `.github/workflows/ci.yml`,
   workflow `name: CI`, jobs named exactly `Quality`, `Tests`, `Tool
   Validation`. These names are a future branch-protection API contract
   — never rename them casually.
2. **`Quality` and `Tests` are intended future required checks; `Tool
   Validation` is never required.** Until a separate, explicitly
   human-approved Phase B step enables branch protection, **none** of
   the three are actually required by GitHub — always describe them as
   "intended future required checks," never as already required.
3. **`Tool Validation` failures are visible, never hidden.** Non-required
   does not mean `continue-on-error: true`. A real-tool regression must
   still show up red on the PR checks list.
4. **`real_llm` never runs automatically.** No workflow sets
   `IAC_AGENT_LLM_PROVIDER`, no model API key, no provider SDK, no LLM
   job. The existing marker's double-guard (env-var `skipif` +
   unconditional `pytest.skip()` in the test body) is untouched.
5. **No credentials, no OIDC, no write permissions.**
   `permissions: contents: read` at workflow level; no
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`/OIDC
   role anywhere in the workflow's own `env:`. (The real-tool test
   fixtures supply their own placeholder AWS values internally — see
   Task 1 — never the workflow file.)
6. **No `terraform apply`/`destroy`, no deployment, no GitHub-source-
   control mutation.** Nothing in this workflow or the code it exercises
   performs any of these.
7. **Python 3.12 only, no matrix.** Matches `requires-python =
   ">=3.12,<3.13"` exactly — verified in `pyproject.toml`.
8. **Terraform pinned to exactly `1.16.1`; Checkov pinned to exactly
   `3.3.13`.** Never `latest` for either — see design §5/§6 for why
   Checkov floating is load-bearing, not stylistic.
9. **No duplicate eval job.** The seven deterministic golden-eval files
   already collect under the `Tests` command (verified: 7 items) — no
   `Eval`/`Golden Evals`/`Architecture Evals` job is ever created.
10. **Branch protection is explicitly out of scope for this
    implementation.** This plan's tasks never call a GitHub
    settings/branch-protection API. Phase B is a separate, later,
    human-approved operation.
11. **No untrusted interpolation into shell.** No `run:` step ever
    interpolates `${{ github.event.pull_request.title }}` or any other
    PR-controlled string directly into a shell command.
12. **Clean-room.** No employer/company names, internal domains, private
    repo names, credentials, tokens, real AWS account IDs, GitLab,
    Atlantis, or `Co-Authored-By` trailers in any file this plan
    produces or proposes.
13. **Git discipline.** Continue on the existing branch
    `docs/batch22-ci-quality-gates-design` (see "Branch strategy"
    below) — no new branch, no worktree. Commit frequently with the
    exact messages given per task. Never push without explicit
    instruction to do so, never force-push, never amend, never rewrite
    history. No `Co-Authored-By` trailer in any commit this plan
    proposes.
14. **Repository verification, not assumption.** Every command below was
    run against this repository before being written into this plan
    (see "Repository verification snapshot").

---

## Repository verification snapshot (re-confirmed at HEAD `6b196a3`)

- `pyproject.toml`: `requires-python = ">=3.12,<3.13"`; one extras
  group, `dev = ["pytest>=8.0", "ruff>=0.6"]`; install command
  `pip install -e ".[dev]"` (no other extras group exists — never
  invent one).
- `.github/` does not exist anywhere in this repository (`find .github
  -type f` returns nothing).
- `PyYAML` is already importable in `.venv` (`6.0.3`, a transitive
  dependency) — usable for a zero-install YAML syntax check.
- `actionlint` and `act` are **not** installed locally; `brew` and `gh`
  (2.89.0) are available.
- `terraform fmt -check -recursive -diff terraform/ tests/terraform/`
  exits `0` today (verified).
- `pytest -m "not real_tool and not real_llm" -q` → **1220 passed, 64
  deselected**, wall-clock **4.46s** (verified, three runs, consistent).
- `pytest -m "not real_tool and not real_llm" --collect-only -q | grep
  -c golden_evals` → **7** (all seven deterministic golden-eval files
  collected under this exact command — the evidence Constraint 9 relies
  on).
- `pytest -m real_tool -q` → **63 passed, 1221 deselected**, wall-clock
  measured at **1575–1622s (~26–27 min)** across three independent
  local runs (two on this machine, one on a fresh worktree with a cold
  provider cache).
- All 30 `real_tool`-marked files carry a
  `pytest.mark.skipif(shutil.which("terraform") is None or
  shutil.which("checkov") is None, ...)` guard (verified by grep across
  every one, zero unguarded).
- `tests/integration/conftest.py:49` —
  `_PLAN_ENV_OVERRIDES = {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}`
  is a **test-fixture-internal** dict, built inside
  `terraform_plan_env_overrides` and passed directly to the
  `TerraformRunner` subprocess call — it is never read from, or
  dependent on, the ambient process/CI-job environment. **The workflow
  file itself never needs to set these values** — this is why Task 1's
  YAML has no `env:` block for AWS credentials at all.
- `docs/terraform-credential-free-plan.md` independently documents and
  empirically verifies the same "placeholder-only, never reaches a real
  AWS API" property (Batch 3 evidence) — this plan does not re-derive
  that, only relies on it.
- `git log --oneline -3` on `docs/batch22-ci-quality-gates-design`:
  `6b196a3 docs: design CI quality gates` (HEAD), on top of `67e4838`
  (verified `main`).

## Branch strategy

**No new branch, no worktree.** Continue directly on the existing
`docs/batch22-ci-quality-gates-design` branch, which currently holds
only the design commit (`6b196a3`). This mirrors the exact precedent
Batch 21 established: design, plan, and every implementation commit for
one batch all land on the same feature branch, which is later published
and opened as a single PR (see Task 3). No `main` commit happens until
that PR is human-reviewed and merged.

---

## Task 1 — Create and locally validate `.github/workflows/ci.yml`

**Files**
- Create: `.github/workflows/ci.yml`

**Verification model for this task** (config, not TDD-over-Python):
- **RED:** prove the workflow does not exist yet and the required
  behavior (a `ci.yml` naming exactly `Quality`/`Tests`/`Tool
  Validation`, running the exact commands below) is absent.
- **GREEN:** create the file: minimum content that satisfies every
  Global Constraint; validate its syntax/content locally (YAML
  parses; `actionlint` — if available — reports no findings; every
  literal command in the file matches a command already verified
  against this repository).
- **REGRESSION:** re-run the exact repository commands the workflow
  will execute (Task 2) to confirm the workflow's `run:` steps are
  byte-for-byte what was already proven to work.

**Exact file content:**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    name: Quality
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install project (dev extras)
        run: pip install -e ".[dev]"

      - name: Ruff
        run: ruff check .

      - name: Set up Terraform 1.16.1
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.16.1"
          terraform_wrapper: false

      - name: Terraform fmt check
        run: terraform fmt -check -recursive -diff terraform/ tests/terraform/

  tests:
    name: Tests
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install project (dev extras)
        run: pip install -e ".[dev]"

      - name: Run deterministic offline suite
        run: pytest -m "not real_tool and not real_llm"

  tool-validation:
    name: Tool Validation
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install project (dev extras)
        run: pip install -e ".[dev]"

      - name: Set up Terraform 1.16.1
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.16.1"
          terraform_wrapper: false

      - name: Install Checkov 3.3.13
        run: pip install checkov==3.3.13

      - name: Run real-tool suite
        run: pytest -m real_tool
```

**Design notes to preserve verbatim (do not "improve" these away):**
- `terraform_wrapper: false` on both `hashicorp/setup-terraform` steps:
  the action's default wrapper script rewrites `terraform`'s
  stdout/stderr to capture action outputs, which would interfere with
  `TerraformRunner`'s own direct subprocess stdout/stderr parsing. This
  keeps the real, unwrapped binary on `PATH`, exactly matching local
  developer behavior.
- The `concurrency.group` key intentionally combines
  `github.event.pull_request.number || github.ref`: for a
  `pull_request`-triggered run this evaluates to the PR number (stable
  and unique per PR even before `github.ref`'s synthetic merge-ref
  value is considered), and for a `push`-triggered run (no PR context)
  it falls back to `github.ref` (`refs/heads/main`). This guarantees
  distinct PRs never share a cancellation group.
- No `env:` block sets any `AWS_*` variable anywhere in this file — see
  "Repository verification snapshot" above for why that is correct, not
  an oversight.
- Three jobs, zero `needs:` — they run fully in parallel; `Quality`/
  `Tests` never wait on `Tool Validation`.
- `actions/checkout@v4`, `actions/setup-python@v5`, and
  `hashicorp/setup-terraform@v3` are pinned to their current stable
  major version tags — `actions/*` are GitHub's own first-party actions,
  and `hashicorp/setup-terraform` is HashiCorp's own official action for
  installing their own product; no third-party/marketplace action of
  unknown provenance is used anywhere. (A stricter future hardening —
  pinning to a full commit SHA instead of a major-version tag — is a
  legitimate follow-up, not required for this batch; note it in the
  final report as a documented, deferred option rather than silently
  deciding it.)

**Steps**

- [ ] **RED:** confirm the workflow does not exist yet:
      `test -f .github/workflows/ci.yml && echo "EXISTS (unexpected)" || echo "ABSENT (expected RED)"`
      — expected output: `ABSENT (expected RED)`.
- [ ] Create `.github/workflows/ci.yml` with exactly the content above.
- [ ] **GREEN, tier 1 (always available):** validate basic YAML syntax:
      `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"`
      — expected: `YAML OK`, no exception.
- [ ] **GREEN, tier 2 (if available):** check whether `actionlint` can
      be installed without friction: `brew list actionlint 2>/dev/null
      || brew install actionlint`. If it installs successfully, run
      `actionlint .github/workflows/ci.yml` — expected: no output (no
      findings). If `brew install actionlint` fails or is undesirable in
      the execution environment, skip this tier and rely on tier 1 plus
      Task 3's real remote validation — note explicitly in the task's
      commit/report which tier was actually used, never silently assume
      tier 2 ran.
- [ ] Confirm every literal `run:` command in the file matches, exactly
      character-for-character, one of: `pip install -e ".[dev]"`,
      `ruff check .`, `terraform fmt -check -recursive -diff terraform/
      tests/terraform/`, `pytest -m "not real_tool and not real_llm"`,
      `pip install checkov==3.3.13`, `pytest -m real_tool` — cross-check
      against the "Repository verification snapshot" section above.
- [ ] Confirm job names are exactly `Quality`, `Tests`, `Tool
      Validation` (the YAML `name:` fields) — grep:
      `grep -n "name:" .github/workflows/ci.yml | grep -E "Quality|Tests|Tool Validation"`
      — expected: three matches, exact strings.
- [ ] Confirm `permissions: contents: read` is the only permissions
      entry: `grep -A2 "^permissions:" .github/workflows/ci.yml` —
      expected: exactly `contents: read`, nothing else.
- [ ] Run `git diff --check` — expected: clean.
- [ ] Commit:
      ```
      feat(ci): add GitHub Actions Quality/Tests/Tool Validation workflow
      ```

---

## Task 2 — Local parity/regression verification, and minimal documentation

**Purpose:** prove, entirely locally, that every command Task 1's
workflow will run on GitHub's runners is exactly the command already
proven to work in this repository — the "regression" step for a
configuration-only change — and add the minimal documentation the
design calls for (no rewrite).

**Files**
- Create: `docs/ci.md`
- Modify: `README.md` (one additional doc-reference, mirroring the
  existing pattern for every other topic doc)

**Steps**

- [ ] Run the exact `Quality` job commands, in order, and record
      pass/fail:
      `.venv/bin/ruff check .` — expected: `All checks passed!`
      `terraform fmt -check -recursive -diff terraform/ tests/terraform/` — expected: exit `0`, no diff output.
- [ ] Run the exact `Tests` job command:
      `.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q`
      — expected: `1220 passed, 64 deselected` (or the current
      equivalent count if the suite has grown since this plan was
      written — the pass bar is zero failures/errors, not a specific
      historical number).
- [ ] Confirm the seven golden-eval files are inside that same
      collection (Constraint 9's evidence, re-verified):
      `.venv/bin/python -m pytest -m "not real_tool and not real_llm" --collect-only -q | grep -c golden_evals`
      — expected: `7`.
- [ ] Run the exact `Tool Validation` job command (this takes ~25–30
      minutes; run in the background and wait for completion rather
      than polling):
      `.venv/bin/python -m pytest -m real_tool -q`
      — expected: `63 passed, 1221 deselected`.
- [ ] Confirm Checkov's pinned version still matches what the empirical
      profile comments assume:
      `.venv/bin/python -c "import subprocess; print(subprocess.run(['checkov','--version'], capture_output=True, text=True).stdout)"`
      — expected: `3.3.13`. If it differs, **stop and report** — do not
      silently re-pin `checkov_profiles.py`'s empirical comments or the
      workflow's version string without a human decision; this is
      exactly the load-bearing-version concern the design flagged.
- [ ] Confirm no `AWS_*` environment variable is required ambient in the
      shell for any of the above (re-run the `Tool Validation` command
      once more inside `env -i PATH="$PATH" HOME="$HOME"` — a minimal
      environment with no inherited `AWS_*`/other variables — to prove
      the test fixtures are genuinely self-contained, not accidentally
      relying on a developer's own `~/.aws` profile):
      `env -i PATH="$PATH" HOME="$HOME" .venv/bin/python -m pytest -m real_tool -q`
      — expected: same result, `63 passed, 1221 deselected`.
- [ ] Run `git diff --check` — expected: clean.
- [ ] Clean-room review over `.github/workflows/ci.yml` and the new
      `docs/ci.md`:
      `grep -niE "gitlab|atlantis|clubhub|royalbeyond|pablo|galeana|@[a-z0-9.-]+\.(corp|internal)" .github/workflows/ci.yml docs/ci.md`
      — expected: no output, or only the repository's own already-public
      `IngMatrix-PGB` handle if it appears at all (see Batch 22 design
      commit's own precedent for why that specific string is not a
      clean-room violation).
- [ ] Write `docs/ci.md` — a short, single-purpose doc (mirroring
      `docs/application.md`/`docs/hitl.md`'s existing size and tone),
      covering exactly:
      - The three jobs (`Quality`, `Tests`, `Tool Validation`) and what
        each runs.
      - That `Quality`/`Tests` are *intended future* required checks —
        not yet required — and `Tool Validation` is never intended to be
        required (network-dependent, ~25–30 minutes).
      - The exact local-parity commands from this task, so a
        contributor can reproduce any CI result offline before pushing.
      - `real_llm` is excluded from all CI by design and always inert —
        one sentence, pointing at
        `docs/superpowers/specs/2026-09-15-structured-architecture-intent-design.md`
        §15.2 for the original rationale.
      - No deployment, no `terraform apply`/`destroy`, no AWS mutation
        occurs anywhere in CI — one sentence.
- [ ] Add exactly one sentence to `README.md`'s existing doc-reference
      list (the paragraph that already lists
      `docs/application.md, docs/hitl.md, docs/source-control.md, ...`)
      appending `docs/ci.md` to that same list with a two-to-four-word
      description, matching the existing sentence's own style — no
      broader README rewrite.
- [ ] Commit:
      ```
      docs(ci): document CI jobs and local parity commands
      ```

---

## Task 3 — Publish the branch, open a PR, and observe real GitHub Actions results

**This is the step that actually proves the design works** — everything
before this is local evidence, which the design and this plan both
treat as necessary but not sufficient (a workflow can be locally
"valid YAML" and still fail on GitHub's actual runners for reasons no
local check can catch: action resolution, runner image differences,
network behavior specific to Actions' own egress).

**Steps**

- [ ] Re-verify before pushing (mirrors the exact pre-push discipline
      already used for Batch 21's publication):
      1. `git status --short` — expected: clean.
      2. `git log --oneline main..HEAD` — expected: exactly the design
         commit (`6b196a3`) plus this batch's own commits (Tasks 1–2),
         no unexpected commits.
      3. `git log main..HEAD --format="%B" | grep -i "co-authored-by"` —
         expected: no output.
      4. `git diff --check main HEAD` — expected: clean.
      5. Re-verify active `gh` account is the repository-owning
         `IngMatrix-PGB` identity (`gh auth status`), switching with
         `gh auth switch --hostname github.com --user IngMatrix-PGB` if
         a different account is currently active — this environment's
         active `gh` account has been observed to change between
         sessions, so re-check immediately before this specific push,
         not from memory of an earlier check.
- [ ] Push (normal, non-force):
      `git push origin docs/batch22-ci-quality-gates-design`
- [ ] Open one PR:
      `gh pr create --repo IngMatrix-PGB/iac-agent-platform --base main --head docs/batch22-ci-quality-gates-design --title "ci: add Quality/Tests/Tool Validation GitHub Actions workflow" --body "<summarize the design + this plan; state explicitly that Quality/Tests are *intended future* required checks, not yet required, and that branch protection is a separate follow-up>"`
- [ ] Wait for all three checks to report a terminal state (not
      "in progress") — `Tool Validation` alone will take ~25–30 minutes;
      do not poll manually, use the harness's background-task
      notification or `gh pr checks --watch`.
- [ ] Inspect and record each job's actual result:
      `gh pr checks <PR number> --repo IngMatrix-PGB/iac-agent-platform`
      — record `Quality`, `Tests`, and `Tool Validation`'s pass/fail
      state and runtime for each.
- [ ] If any job fails for a reason attributable to the CI
      configuration itself (not a real code defect) — e.g. an action
      version resolution issue, a runner-image difference, a
      `PATH`/tool-discovery problem specific to `ubuntu-latest` — fix it
      with a normal, reviewable commit on the same branch (never
      `--amend`, never force-push) and push again. This is Task 4's job
      if the fix is non-trivial; a one-line, obviously-correct fix may
      stay in this task.
- [ ] Do **not** merge the PR in this task. Do **not** enable branch
      protection. Do **not** mark any check as required.

---

## Task 4 — Remote-failure correction loop (only if needed) and final evidence report

**This task exists conditionally.** If Task 3's three checks all pass
cleanly on the first real run, this task collapses to just the "final
evidence report" bullet below — do not manufacture busywork to fill a
task slot that isn't needed.

**Steps**

- [ ] If Task 3 required one or more fix-and-repush cycles, summarize
      each: what failed, why (root cause, not just symptom), what
      commit fixed it, and confirm the corrected run is green.
- [ ] Final evidence report (to the human reviewer, not a file this plan
      creates): PR URL, final commit SHA on the branch, each job's final
      status and runtime, confirmation that `Quality`/`Tests` are
      described only as "intended future required checks" everywhere
      (PR description, `docs/ci.md`), and an explicit statement that
      branch protection has not been touched.
- [ ] **STOP.** Await human review and merge decision. Do not proceed to
      Phase B (branch protection) or any further batch without a
      separate, explicit human approval.

---

## Local validation command reference (for quick copy-paste during Tasks 1–2)

```bash
# Quality
ruff check .
terraform fmt -check -recursive -diff terraform/ tests/terraform/

# Tests (required-designate)
pytest -m "not real_tool and not real_llm"

# Tool Validation (non-required)
pytest -m real_tool

# Golden-eval coverage proof
pytest -m "not real_tool and not real_llm" --collect-only -q | grep -c golden_evals   # expect 7

# Workflow YAML syntax (tier 1, always available)
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"

# Workflow static analysis (tier 2, if actionlint installed)
actionlint .github/workflows/ci.yml

# Pre-commit hygiene
git diff --check
git status --short
```

## Security / supply-chain review

- **Actions used:** `actions/checkout` (GitHub first-party),
  `actions/setup-python` (GitHub first-party), `hashicorp/setup-terraform`
  (HashiCorp's own official action for their own product). No
  third-party/community marketplace action of unverified provenance is
  used anywhere in this workflow.
- **Pinning:** major-version tags (`@v4`, `@v5`, `@v3`) — the common,
  low-friction baseline; SHA-pinning is a stricter option available as a
  documented future hardening step, not adopted this batch (noted, not
  silently decided either way).
- **Permissions:** `contents: read` only, workflow-level, inherited by
  all three jobs — no job overrides it upward.
- **Secrets:** none referenced anywhere in the workflow file (no
  `secrets.*` context access at all).
- **Untrusted input:** no `${{ github.event.* }}` value is interpolated
  into any `run:` shell block; the one context expression used outside
  a `run:` block (`concurrency.group`) is evaluated by the Actions
  runtime itself, not passed through a shell.
- **AWS credentials:** none in the workflow's own `env:`; the only
  placeholder AWS values anywhere in the whole chain are internal to the
  existing, already-reviewed `tests/integration/conftest.py` fixture
  (Batch 3 precedent, re-verified in Task 2) — this plan changes nothing
  about that mechanism.

## Coverage cross-reference (design requirement → plan location)

| Design/task requirement | Plan location |
|---|---|
| Workflow name `CI`, jobs `Quality`/`Tests`/`Tool Validation` | Task 1 exact YAML |
| `contents: read` only | Task 1 YAML + Task 1 verification step |
| Triggers: `pull_request`+`push` to `main`, no schedule | Task 1 exact YAML |
| Concurrency, robust group expression | Task 1 exact YAML + design note |
| Python 3.12 pin, no matrix | Task 1 exact YAML (`python-version: "3.12"`) |
| Terraform 1.16.1 pin, official action | Task 1 exact YAML (`hashicorp/setup-terraform@v3`) |
| Checkov 3.3.13 pin | Task 1 exact YAML (`pip install checkov==3.3.13`) |
| Install command `pip install -e ".[dev]"` | Task 1 exact YAML, every job |
| `Quality` runs ruff + terraform fmt | Task 1 exact YAML |
| `Tests` runs the deterministic marker filter | Task 1 exact YAML |
| `Tool Validation` runs `real_tool`, non-required, failure-visible (no `continue-on-error`) | Task 1 exact YAML (no such key present) |
| No duplicate eval job | Task 2, golden-eval collection proof (7) |
| `real_llm` never automatic | Global Constraint 4; no reference anywhere in the YAML |
| No apply/destroy, no deployment | Security review; Global Constraint 6 |
| Workflow YAML validation strategy | Task 1, tier 1 (PyYAML) + tier 2 (actionlint, best-effort) |
| Remote validation explicitly separated from local | Task 3, entirely |
| Branch protection excluded from implementation | Global Constraint 10; Task 3 explicit non-action; Task 4 STOP |
| Minimal documentation only | Task 2, `docs/ci.md` + one README sentence |
| Branch/worktree strategy | "Branch strategy" section |

## Self-review checklist

- [x] Every design requirement (§19 of the design spec) maps to a
      concrete step above — see cross-reference table.
- [x] No placeholders: every command, file path, and job name is
      literal and exact, verified against the repository before being
      written here.
- [x] Workflow/job names consistent everywhere they appear in this plan
      (`CI` / `Quality` / `Tests` / `Tool Validation`).
- [x] Version pins consistent: Python `3.12` everywhere; Terraform
      `1.16.1` in both places it's installed; Checkov `3.3.13` exactly
      once, in `Tool Validation` only.
- [x] Every command matches a command actually run against this
      repository during planning (see "Repository verification
      snapshot").
- [x] `Quality`/`Tests` have no `needs:` on `Tool Validation` — fully
      independent.
- [x] `Tool Validation` is non-required (documented only as future
      "not required" in `docs/ci.md`) but has no `continue-on-error`.
- [x] `real_llm` is never referenced by the workflow file at all.
- [x] No credential, secret, or OIDC permission anywhere in the design.
- [x] Least privilege (`contents: read`) verified as the only
      permission.
- [x] No `apply`/`destroy` anywhere in the proposed workflow or its
      target commands.
- [x] Offline evals proven covered exactly once (7 golden-eval files
      under the `Tests` command), no second job.
- [x] Branch protection excluded from every task — Task 3 and Task 4
      both say so explicitly.
- [x] Remote validation (Task 3) is a distinct, separate step from local
      validation (Tasks 1–2), never conflated.
- [x] No production/test/Terraform implementation occurs in this
      planning batch — this document is the only artifact.

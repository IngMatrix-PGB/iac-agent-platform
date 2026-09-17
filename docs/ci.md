# Continuous integration (Batch 22)

One GitHub Actions workflow, `.github/workflows/ci.yml` (display name
`CI`), runs on every pull request and every push to `main`. It has
three independent jobs — none depends on another (`needs:` is never
set), so a slow job never blocks the fast ones.

## Quality

Runs `ruff check .` and `terraform fmt -check -recursive -diff
terraform/ tests/terraform/`. Fast, credential-free, no network beyond
installing Python/Terraform themselves. **Intended future required
check** — not yet enforced by branch protection.

## Tests

Runs `pytest -m "not real_tool and not real_llm"` — the project's full
deterministic, offline test suite. This already transitively includes
every golden-eval scenario (SQS, S3, DynamoDB, Lambda, API Gateway, both
compositions, and the architecture-intent resolver) — there is no
separate eval job. Fast (a few seconds of actual test execution),
credential-free, no network. **Intended future required check** — not
yet enforced by branch protection.

## Tool Validation

Runs `pytest -m real_tool` — the same logic re-verified against the
*real* Terraform (`1.16.1`) and Checkov (`3.3.13`) binaries, pinned
exactly (never `latest`, since Checkov's own ruleset changes between
versions and this project's empirically-derived finding counts are tied
to `3.3.13`). This job needs outbound network access to the public
Terraform Registry (to download the `hashicorp/aws` provider) but no
credentials — every Terraform-plan-touching test supplies its own
placeholder `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` values internally
and never contacts a real AWS API (see
`docs/terraform-credential-free-plan.md`). Currently takes roughly
25–30 minutes, the large majority of it spent on provider download and
real `terraform`/`checkov` subprocess calls. **Never intended to become
a required check** — it runs and reports on every trigger, and a
regression here fails visibly (no `continue-on-error`), but it does not
block a PR from merging.

## What CI never does

No step anywhere runs `terraform apply` or `terraform destroy`, deploys
anything, mutates a real GitHub repository, or requires an AWS account.
The `real_llm` pytest marker is excluded from every job in this
workflow and remains inert everywhere: no job sets
`IAC_AGENT_LLM_PROVIDER`, and the one `real_llm`-marked test skips
unconditionally regardless (see
`docs/superpowers/specs/2026-09-15-structured-architecture-intent-design.md`
§15.2). The workflow requests only `contents: read` — no write, no
`pull-requests: write`, no `id-token: write`, no secrets of any kind.

## Reproducing CI locally

```bash
ruff check .
terraform fmt -check -recursive -diff terraform/ tests/terraform/
pytest -m "not real_tool and not real_llm"
pytest -m real_tool   # needs terraform 1.16.1 and checkov 3.3.13 on PATH
```

## Branch protection

Not enabled yet. A future, separately human-approved change may make
`Quality` and `Tests` required status checks on `main` once this
workflow has proven itself on real pull requests; `Tool Validation` is
not intended to become required under the current design (see
`docs/superpowers/specs/2026-09-16-ci-quality-gates-design.md`).

# Continuous integration

`.github/workflows/ci.yml` runs on every pull request to `main` and every push to `main`. Quality, Tests, Frontend, and Classify do not depend on each other. Bootstrap Validation and ten real-tool shard jobs depend on Classify. Every job runs on `ubuntu-24.04`.

## Quality

Ruff, `terraform fmt -check` for `terraform/` and `tests/terraform/`, and the attribution check in `scripts/check_commit_attribution.py`. The attribution check rejects `Co-Authored-By`, `Generated-By`, and a Cursor or Claude footer in commit messages and, on pull requests, in the pull request body.

`Quality` is a required status check on `main`.

## Tests

```bash
pytest -m "not real_tool and not real_llm and not docker"
```

This is the deterministic suite, including the golden evals. It does not need credentials. `Tests` is a required status check on `main`.

## Validation shards

Real-tool validation is blast-radius-specific. Classify selects the shard that owns a changed resource and the transitive shards that consume it. A resource-specific pull request does not run the full real-tool suite.

The full shard union runs for a shared or high-blast-radius product path, a workflow change, an empty or unreadable diff, or a classifier failure. A failed Classify job runs every shard. Each shard runs `pytest -m real_tool` plus only its owned files, against Terraform 1.16.1 and Checkov 3.3.13 installed from `ci/requirements-checkov.txt`. Shards restore the private Terraform plugin cache and do not save it. Only the Provider Cache job, on a push to `main`, saves that same path, and only on a cache miss. The tests need the public Terraform Registry and use placeholder AWS credentials. They do not call a real AWS API. See `docs/terraform-credential-free-plan.md`.

The monolithic Tool Validation job was the migration control. On run [37124356929](https://github.com/IngMatrix-PGB/iac-agent-platform/actions/runs/37124356929), its 79 passed tests matched the shard union for the same 39 files. That job is removed. The suite was not reduced.

## Provider Cache

Provider Cache runs only on a push to `main`. It restores `${{ runner.temp }}/tf-plugin-cache`, initializes a copy of `terraform/modules/s3` with `terraform init -backend=false`, and saves that same directory when the restore was a cache miss. It does not save Terraform state.

## Frontend

In `ui/`: `npm ci`, `npm test`, and `npm run build`. The job is not a required check.

## Classify

`Classify` always runs. It writes a step summary and records which validation shards a diff selects. Shard jobs read those outputs. They do not match paths in the workflow.

## Bootstrap Validation

Bootstrap Validation runs `pytest -m real_bootstrap_tool` when Classify selects bootstrap, or when Classify itself fails. It is the existing credential-free plan test. It does not call AWS and does not change the module.

## What CI never does

No job runs `terraform apply` or `terraform destroy`, deploys to AWS, or publishes a pull request. The workflow permission is `contents: read`. It does not request `id-token: write`. The `real_llm` marker is excluded. The one real-model eval also skips when `IAC_AGENT_LLM_PROVIDER` is unset. See `docs/intent.md` and `docs/aws-plan-boundary.md`.

## Reproducing CI locally

```bash
ruff check .
terraform fmt -check -recursive -diff terraform/ tests/terraform/
pytest -m "not real_tool and not real_llm and not docker"
pytest -m real_tool
pytest -m real_bootstrap_tool
```

Frontend: `npm ci && npm test && npm run build` from `ui/`.

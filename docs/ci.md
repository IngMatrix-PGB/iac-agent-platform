# Continuous integration

`.github/workflows/ci.yml` runs on every pull request to `main` and every push to `main`. The jobs do not depend on each other. Every job runs on `ubuntu-24.04`.

## Quality

Ruff, `terraform fmt -check` for `terraform/` and `tests/terraform/`, and the attribution check in `scripts/check_commit_attribution.py`. The attribution check rejects `Co-Authored-By`, `Generated-By`, and a Cursor or Claude footer in commit messages and, on pull requests, in the pull request body.

`Quality` is a required status check on `main`.

## Tests

```bash
pytest -m "not real_tool and not real_llm and not docker"
```

This is the deterministic suite, including the golden evals. It does not need credentials. `Tests` is a required status check on `main`.

## Tool Validation

`pytest -m real_tool` runs the same behavior against Terraform 1.16.1 and Checkov 3.3.13. It needs the public Terraform Registry and uses placeholder AWS credentials. It does not call a real AWS API. See `docs/terraform-credential-free-plan.md`. The job reports on every run and is not a required check.

## Frontend

In `ui/`: `npm ci`, `npm test`, and `npm run build`. The job is not a required check.

## What CI never does

No job runs `terraform apply` or `terraform destroy`, deploys to AWS, or publishes a pull request. The workflow permission is `contents: read`. It does not request `id-token: write`. The `real_llm` marker is excluded. The one real-model eval also skips when `IAC_AGENT_LLM_PROVIDER` is unset. See `docs/intent.md` and `docs/aws-plan-boundary.md`.

## Reproducing CI locally

```bash
ruff check .
terraform fmt -check -recursive -diff terraform/ tests/terraform/
pytest -m "not real_tool and not real_llm and not docker"
pytest -m real_tool
```

Frontend: `npm ci && npm test && npm run build` from `ui/`.

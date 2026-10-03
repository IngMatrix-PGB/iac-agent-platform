# CI validation architecture

Status: design, not implemented.

The end state replaces the single Tool Validation job with a blast-radius classifier and parallel real-tool shards. The migration keeps that job until the shard union is proven equal to today's suite. This design does not change product runtime, AWS IAM, the OIDC trust policy, or branch protection.

This branch is `origin/main` at `2f611ef`. That tree has no `aws-plan` job. This design does not add one. If the implementation branch already contains the opt-in identity check, that job stays as it is.

Measured baseline, PR #22 run `37062242107`, job `111021403734`:

| Slice | Time |
| --- | ---: |
| Tool Validation job | 15m 31s |
| `pytest -m real_tool` | 14m 59s |
| Result | 79 passed, 2 skipped, 1737 deselected |
| Checkout through Checkov install | about 27s |

The 899 seconds are serial credential-free `terraform init` / `plan` / `show`. Checkov adds a few seconds on workflow and golden tests. Pip is already cached. The provider plugin cache exists only inside one pytest process.

`tests/integration/test_bootstrap_aws_oidc_terraform.py` is `real_bootstrap_tool`, not `real_tool`. The Tests job does not install Terraform, so that test is skipped. Tool Validation does not select the marker. CI never runs it.

Required contexts on `main` stay `Quality` and `Tests`, strict, until a later explicit decision. Tool Validation is not required today.

## Invariant

A change to a resource, module, or renderer runs:

1. the shard that owns that resource
2. every shard that contains a transitive consumer of that resource, including compositions
3. Security Validation when that change affects security or profile behavior for that resource

It does not run unrelated resource families.

A change to SQS runs the SQS shard, the serverless-worker shard, and Security Validation, because those tests render SQS. It does not run the S3, ECR, or standalone Lambda shards.

A change to Lambda runs the Lambda shard plus `api_lambda`, `api_lambda_dynamodb`, and `serverless_worker`.

A change to DynamoDB runs the DynamoDB shard plus `api_lambda_dynamodb` and `serverless_worker`.

A change to S3 runs the S3 shard only. No composition module source points at `terraform/modules/s3`.

A change to ECR runs the ECR shard only.

A change to API Gateway runs the API Gateway shard plus `api_lambda` and `api_lambda_dynamodb`.

The Security Validation job runs when the selected set includes the `security` shard. SQS selects it because those five tests render SQS. A change under `src/iac_agent/security/` or `src/iac_agent/policies/` selects every shard, including `security`, because those packages are shared. A DynamoDB, Lambda, S3, or ECR module change does not select that job. Profile coverage for those resources lives in their own golden tests.

Full validation is the union of every shard. That union executes the current `real_tool` inventory with no omissions and no duplicates. Full validation remains available for shared code, workflow edits, unknown paths, and classifier failure.

## Dependency map

One table is the classifier input. Workflow `if` expressions do not restate these edges.

Each `real_tool` file belongs to exactly one shard. Edges say which modules a shard consumes. The classifier turns a changed module into the set of shards that list that module.

| Shard | Owns these `real_tool` files | Consumes |
| --- | --- | --- |
| `s3` | `test_s3_renderer_terraform.py`, `test_s3_golden_real_tool_eval.py`, `test_s3_workflow_integration.py`, `test_s3_workflow_persistence.py` | `s3` |
| `sqs` | `test_sqs_renderer_terraform.py`, `test_sqs_golden_real_tool_eval.py`, `test_sqs_workflow_integration.py`, `test_sqs_workflow_persistence.py`, `test_sqs_workflow_hitl.py` | `sqs` |
| `dynamodb` | `test_dynamodb_renderer_terraform.py`, `test_dynamodb_golden_real_tool_eval.py`, `test_dynamodb_workflow_integration.py`, `test_dynamodb_workflow_persistence.py` | `dynamodb` |
| `ecr` | `test_ecr_renderer_terraform.py`, `test_ecr_golden_real_tool_eval.py`, `test_ecr_workflow_persistence.py` | `ecr` |
| `lambda` | `test_lambda_renderer_terraform.py`, `test_lambda_golden_real_tool_eval.py`, `test_lambda_workflow_integration.py`, `test_lambda_workflow_persistence.py` | `lambda` |
| `api_gateway` | `test_api_gateway_renderer_terraform.py` | `api_gateway` |
| `api_lambda` | `test_api_lambda_renderer_terraform.py`, `test_api_lambda_golden_real_tool_eval.py`, `test_api_lambda_workflow_integration.py`, `test_api_lambda_workflow_persistence.py` | `api_gateway`, `lambda` |
| `api_lambda_dynamodb` | `test_api_lambda_dynamodb_renderer_terraform.py`, `test_api_lambda_dynamodb_golden_real_tool_eval.py`, `test_api_lambda_dynamodb_workflow_persistence.py` | `api_gateway`, `lambda`, `dynamodb` |
| `serverless_worker` | `test_serverless_worker_renderer_terraform.py`, `test_serverless_worker_golden_real_tool_eval.py`, `test_serverless_worker_workflow_integration.py`, `test_serverless_worker_workflow_persistence.py`, `test_application_composition.py`, `test_cli_real_tool.py` | `sqs`, `lambda`, `dynamodb` |
| `security` | `test_checkov_integration.py`, `test_security_gate_integration.py`, `test_platform_policy_integration.py`, `test_plan_analyzer_integration.py`, `test_terraform_runner_integration.py` | `sqs` |

That is 39 files. A direct count of `pytest.mark.real_tool` on this tree is the same 39 files, and the PR #22 log showed 79 tests. `test_cli_real_tool.py` renders a serverless worker. `test_application_composition.py` renders both a standalone SQS queue and a serverless worker; the file still has one shard, called out below. The five `security` files render SQS, so an SQS change selects them as consumers. An S3 change does not.

Renderer and module paths select the module, then the shards that consume it:

| Path prefix | Module |
| --- | --- |
| `terraform/modules/s3/` | `s3` |
| `terraform/modules/sqs/` | `sqs` |
| `terraform/modules/dynamodb/` | `dynamodb` |
| `terraform/modules/ecr/` | `ecr` |
| `terraform/modules/lambda/` | `lambda` |
| `terraform/modules/api_gateway/` | `api_gateway` |
| `src/iac_agent/providers/aws/s3/` | `s3` |
| `src/iac_agent/providers/aws/sqs/` | `sqs` |
| `src/iac_agent/providers/aws/dynamodb/` | `dynamodb` |
| `src/iac_agent/providers/aws/ecr/` | `ecr` |
| `src/iac_agent/providers/aws/lambda_function/` | `lambda` |
| `src/iac_agent/providers/aws/api_gateway/` | `api_gateway` |
| `src/iac_agent/compositions/api_lambda/` | shard `api_lambda` directly |
| `src/iac_agent/compositions/api_lambda_dynamodb/` | shard `api_lambda_dynamodb` directly |
| `src/iac_agent/compositions/serverless_worker/` | shard `serverless_worker` directly |
| `tests/terraform/s3/` | `s3` |
| `tests/terraform/sqs/` | `sqs` |
| `src/iac_agent/providers/aws/kms.py` | `s3` and `sqs` |

A composition-directory change runs that composition shard only. Standalone resource tests do not consume the composition package.

`kms.py` is imported by the S3 and SQS contracts. The DynamoDB contract mentions that helper and does not import it, so a `kms.py` change does not select DynamoDB. A test asserts the import set equals `{s3, sqs}`. A new importer with no row fails that test, and until the row exists the path is unknown, which selects full validation.

`test_application_composition.py` contains one SQS plan, one serverless-worker plan, and one SQLite lifecycle test. The file has one shard, `serverless_worker`. An SQS change still runs it, because SQS selects that shard. A Lambda or DynamoDB change also runs the SQS plan inside the file. That is extra work inside a shard the change already requires. Splitting the file is out of scope.

These prefixes select every shard, because one file serves every family. `checkov_profiles.py` and `composition_checkov_profiles.py` are shared. A path cannot tell which resource branch changed. The same is true of the shared provider files `src/iac_agent/providers/aws/renderer.py`, `resource.py`, `terraform_render.py`, and `src/iac_agent/providers/aws/__init__.py`. `renderer.py` dispatches every resource type.

- `src/iac_agent/graph/`
- `src/iac_agent/execution/`
- `src/iac_agent/security/`
- `src/iac_agent/policies/`
- `src/iac_agent/app/`
- `.github/workflows/`

A change under `src/iac_agent/security/` also matches rule 3 for every resource, which is the same full set.

A changed `real_tool` file selects its owning shard only.

`docs/`, `README.md`, and `ui/` select no real-tool shard. `Quality` and `Tests` still run. `ui/` also runs Frontend.

`bootstrap/aws-oidc/` and `tests/integration/test_bootstrap_aws_oidc_terraform.py` select Bootstrap Validation and no product shard.

Any other path, including a new module directory, selects full validation: every real-tool shard. It does not by itself select Frontend or Bootstrap Validation.

A diff is the union of its paths. One shared, unknown, or workflow path promotes that diff to full validation. Docs plus an S3 module change select the S3 shard only.

## Classifier

`scripts/ci_classify.py` reads the changed-path list and prints one boolean per shard plus `bootstrap` and `frontend`. The workflow does not duplicate the table.

Full validation is every real-tool shard. These cases select it:

- the script exits non-zero
- the diff is empty or cannot be listed
- a path matches no rule
- any path is under `.github/workflows/`
- any path is under the shared prefixes above

A workflow diff or a classifier failure also runs Bootstrap Validation and Frontend. Those jobs are not part of the real-tool union. A workflow edit is how their `if` conditions would be removed, so the proof of that edit runs them. An unknown product path does not.

Tests, all in the deterministic suite:

- every `real_tool` file belongs to exactly one shard
- the union of shard files equals the collected `real_tool` file inventory, with no omissions and no duplicates
- a collection check shows those files contain the current `real_tool` tests and no others
- every directory in `terraform/modules/` maps to one module
- SQS selects `sqs`, `serverless_worker`, and `security`, and does not select `s3`, `ecr`, or `lambda`
- Lambda selects `lambda`, `api_lambda`, `api_lambda_dynamodb`, and `serverless_worker`, and does not select `s3` or `ecr`
- DynamoDB selects `dynamodb`, `api_lambda_dynamodb`, and `serverless_worker`, and does not select `s3` or `sqs`
- S3 selects `s3` only
- ECR selects `ecr` only
- API Gateway selects `api_gateway`, `api_lambda`, and `api_lambda_dynamodb` only
- `kms.py` selects `s3`, `sqs`, `serverless_worker`, and `security`, and does not select `lambda`, `dynamodb`, or `ecr`
- the importers of `validate_kms_key_id` are exactly the S3 and SQS contracts
- an unknown path selects every real-tool shard and does not select Frontend or Bootstrap Validation
- a workflow path selects every real-tool shard, Bootstrap Validation, and Frontend
- a simulated classifier failure selects every real-tool shard, Bootstrap Validation, and Frontend

The map fails closed: a module directory with no row is an unknown path.

## Jobs

`Quality`, `Tests`, and `Classify` always run. They have no path condition.

`Classify` writes a step summary naming the domains, the jobs that will run, and the jobs that will not, with the path reason.

Shard jobs, each on its own runner, each with its own `TF_PLUGIN_CACHE_DIR`:

| Job name | Shard |
| --- | --- |
| Terraform — S3 | `s3` |
| Terraform — SQS | `sqs` |
| Terraform — DynamoDB | `dynamodb` |
| Terraform — ECR | `ecr` |
| Terraform — Lambda | `lambda` |
| Terraform — API Gateway | `api_gateway` |
| Terraform — API Lambda | `api_lambda` |
| Terraform — API Lambda DynamoDB | `api_lambda_dynamodb` |
| Terraform — Serverless Worker | `serverless_worker` |
| Security Validation | `security` |
| Bootstrap Validation | bootstrap plan test |
| Frontend | `ui/` |
| AWS Plan | not part of this design |

No shard uses `pytest-xdist`. The provider cache is not safe for concurrent writers, and each job is already a separate process.

Bootstrap Validation installs Terraform 1.16.1 and runs `tests/integration/test_bootstrap_aws_oidc_terraform.py` only. That test is fmt, init, validate, and `terraform test` with the OIDC data source overridden. It does not call AWS and does not apply. `Quality` does not fmt `bootstrap/aws-oidc/`. This job is what covers that fmt.

No job gains `terraform apply` or `terraform destroy`. This design does not add or edit an `aws-plan` job.

## Caching

| Cache | Key | Who saves |
| --- | --- | --- |
| pip | existing `setup-python` hash | unchanged |
| Checkov 3.3.13 | a pinned requirements file included in that hash | with pip |
| AWS provider | Terraform 1.16.1 plus the `hashicorp/aws` constraint | `main` only |
| npm | existing Frontend lockfile hash | unchanged |

Pull requests restore the provider cache and do not save it. A pull request cannot replace the `main` cache. A constraint change misses the key. Each shard copies the restored provider into a private directory before pytest. The cache removes the cold download. It does not remove the per-test plan.

## What a diff runs

| Diff | Jobs besides Quality, Tests, and Classify |
| --- | --- |
| Docs only | none |
| UI only | Frontend |
| Bootstrap only | Bootstrap Validation |
| One module | the shards whose Consumes column lists that module |
| `kms.py` | `s3`, `sqs`, `serverless_worker`, `security` |
| Shared runtime | every real-tool shard |
| Workflow, or classifier failure | every real-tool shard, Bootstrap Validation, and Frontend |
| Unknown product path | every real-tool shard |
| Docs plus one module | that module's shards only |

Docs-only still runs Tests. Doc assertions live there, and that job was 44 seconds, inside the one-minute target. UI-only still runs Tests. Frontend was 23 seconds, so the critical path stays Tests.

## Expected critical path

Times are the PR #22 measurements, plus about 30 seconds of setup on a shard runner. Shards for one diff run in parallel, so the path is the slowest selected shard, not the sum.

| Pull request | Slowest selected work | Target |
| --- | --- | --- |
| Docs only | Tests, 44s | ≤ 1 minute |
| UI only | Tests, 44s | ≤ 2 minutes |
| Bootstrap only | the credential-free bootstrap test, about 20s locally, plus CI setup and a possible cold provider fetch | ≤ 2 minutes |
| S3 only | S3 shard, about 68s plus setup | ≤ 6 minutes |
| SQS only | Serverless Worker shard, about 123s; Security Validation runs beside it | ≤ 6 minutes |
| Lambda only | API Lambda DynamoDB shard, about 127s, beside Lambda, API Lambda, and Serverless Worker | ≤ 6 minutes |
| Full validation | the same slowest shard, about 127s plus setup | ≤ 6 minutes |

The merge gate stays `Quality` and `Tests` through this work. Those were 29 seconds and 44 seconds.

## Migration

Action major-version upgrades are not part of this implementation. The Node 20 warning on `actions/checkout@v4`, `actions/setup-python@v5`, and `hashicorp/setup-terraform@v3` stays until a later pull request. Current majors exist and their inputs are not assumed compatible here.

1. Pin `ubuntu-24.04`. The measured runner image was already Ubuntu 24.04. `Quality` and `Tests` keep their names. The monolithic Tool Validation job stays.
2. Add the classifier in report-only mode. Nothing is skipped.
3. Add Bootstrap Validation beside Tool Validation.
4. Add the shard jobs. Tool Validation still runs the full `real_tool` suite.
5. Prove the shard union equals that suite: same files, no duplicates, and the collected test count matches.
6. Only then remove the monolithic Tool Validation job.
7. Required-check changes are a separate explicit decision. Shard names are not added to branch protection in this work.

Do not use workflow-level `paths-ignore`. That can skip `Quality` or `Tests`.

A same-repository pull request can edit the classifier and `ci.yml` together. Phase 1 does not claim otherwise. Keeping the required names `Quality` and `Tests` preserves today's merge gate. Shards are non-required, which is the same exposure as today's non-required Tool Validation job. Making a shard required later, under its final name, is what would make deleting that job block a merge.

## Out of scope

- Product runtime changes
- `terraform apply` or `terraform destroy`
- AWS IAM, OIDC trust, or `IaCPlanRole` permissions
- `pytest-xdist`
- Upgrading GitHub Action major versions
- Changing branch protection
- Running a real AWS Terraform plan

## Acceptance

- A module change runs its owning shard and the consumer shards in the table, and does not run unrelated families.
- An S3-only diff does not run Lambda, DynamoDB, SQS, or composition shards.
- The union of shard membership equals the `real_tool` file inventory, with a test that fails on an omission or a duplicate.
- Those files' collected tests equal the current `real_tool` collection.
- An unknown product path runs every real-tool shard and does not run Frontend or Bootstrap Validation.
- A workflow diff and a classifier failure run every real-tool shard, Bootstrap Validation, and Frontend.
- A `bootstrap/aws-oidc/` diff runs Bootstrap Validation in CI.
- No new job runs `terraform apply` or `terraform destroy`.
- `Quality` and `Tests` remain the required contexts for the whole migration.
- The monolithic Tool Validation job remains until the union proof exists.

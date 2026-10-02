# Deterministic evals

Unit tests check individual modules. Evals check product behavior with a versioned input and a versioned expected outcome. The dataset is JSON under `evals/datasets/`. The test suite checks that the eval runner and evaluators behave. The scenarios check the product.

No deterministic eval calls a paid model API, the network, or AWS. A test patches out `subprocess` and the suite still completes. Scenarios that need the real Terraform or Checkov binaries are marked `real_tool` and are not part of the fast suite.

## Datasets

| Dataset | What it exercises |
| --- | --- |
| `sqs_golden.json` | SQS contract, render, and security outcomes |
| `s3_golden.json` | S3 |
| `dynamodb_golden.json` | DynamoDB |
| `lambda_golden.json` | Lambda and its execution role |
| `ecr_golden.json` | ECR |
| `serverless_worker_golden.json` | SQS → Lambda → DynamoDB |
| `api_lambda_golden.json` | API Gateway → Lambda |
| `api_lambda_dynamodb_golden.json` | API Gateway → Lambda → DynamoDB |
| `architecture_intent_resolver_golden.json` | Deterministic resolver allowlist |
| `architecture_intent_nl_golden.json` | Natural language to `ArchitectureIntent`, with an injected interpreter |

Each file is `{"version": 1, "scenarios": [...]}` and contains no secrets.

Resource and composition scenarios record whether the input is valid and, when it is, the fields and security status the pipeline must produce. Invalid inputs must fail at the contract boundary. They are not rendered.

Typical evaluators are contract validity, the expected fields, byte-identical rendering of the same spec twice, and security status against a typed plan summary plus a fixed Checkov result. They do not shell out to Terraform or Checkov. The resolver dataset checks the allowlist in `docs/intent.md`. The natural-language dataset checks schema, semantic fields, resolver compatibility, and that the interpreter result does not carry Terraform or approval authority. Its runner takes an interpreter as an argument. The deterministic run does not construct a provider client.

## How to run

The deterministic scenarios run with the rest of the offline suite:

```bash
pytest -m "not real_tool and not real_llm and not docker"
```

`tests/integration/` contains one golden-eval module per dataset. One SQS scenario also has a `real_tool` module that runs real Terraform and Checkov when those binaries are on `PATH`.

`tests/integration/test_architecture_intent_nl_real_model_eval.py` is the only test that may construct a real interpreter. It is marked `real_llm` and skips unless `IAC_AGENT_LLM_PROVIDER` is set. CI does not set that variable and excludes the marker.

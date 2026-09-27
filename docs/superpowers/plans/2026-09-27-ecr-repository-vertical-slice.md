# Batch 27 implementation plan — ECR repository vertical slice

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone private ECR repository (`ResourceType.ECR`) that resolves from `STORAGE + {CONTAINER_REGISTRY}`, with AES256 encryption, immutable tags and scan-on-push by default, and a fail-closed CLI label.

**Architecture:** One new contract, one trusted `aws_ecr_repository` module, and one renderer, registered through the existing explicit `match` / `dict[ResourceType, ...]` sites. No composition type. No registry refactor. The interpreter schema widens with the `Capability` enum; the hand-written OpenAI prompt gets one orthogonality sentence.

**Tech Stack:** Python 3.12, Pydantic, Terraform `>= 1.5.0`, `hashicorp/aws ~> 6.0`, pytest, Ruff, Checkov (Gate B only).

Design: `docs/superpowers/specs/2026-09-27-ecr-repository-vertical-slice-design.md`
(closure commit on `docs/batch27-ecr-repository-design`, re-verified
against implementation baseline `037edf6`). Writing this plan does not
authorize implementation. Gate A and Gate B start only after a separate
explicit authorization.

## Global Constraints

- ECR is `ResourceType.ECR = "ecr"`, not a `CompositionType`.
- Intent tuple: `WorkloadType.STORAGE`, any `InteractionPattern`, `frozenset({Capability.CONTAINER_REGISTRY})` → `EcrResourceSpec`, `matched_pattern="storage+container_registry"`. No clarification arm.
- Do not reinterpret `Capability.OBJECT_STORAGE`. Any other `STORAGE` capability set stays `UnsupportedReason.UNSUPPORTED_CAPABILITY`.
- Contract fields: ECR-valid `name`; `image_tag_mutability` default `IMMUTABLE`; `scan_on_push` default `True`; `EcrEncryptionSpec.enabled=True` rejected when `False` by a field validator; no `kms_key_id`.
- Repository name regex, anchored, length 2–256 checked separately: `^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*$`. A leading digit is valid under this regex.
- Policy IDs: `ECR_ENCRYPTION_REQUIRED`, `ECR_SCAN_ON_PUSH_RECOMMENDED`, `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED`. AES256 is the contract, not a WARN.
- Trusted module: one `aws_ecr_repository`. `encryption_type = "AES256"` is hardcoded. No `force_delete`, no KMS resource, no lifecycle policy, no repository policy, no exclusion filter.
- CLI: replace the standalone `return "s3"` with `_STANDALONE_RESOURCE_LABELS[resource_type_of(spec)]`. Do not add only an ECR branch above that return.
- Checkov: Gate A registers `skipped_checks=()`. Do not invent skip IDs. Gate B freezes only empirical findings.
- No `terraform apply`, no `terraform destroy`, no real AWS credentials, no AWS mutation, no OpenAI call, no GitHub mutation.
- Do not edit Batch 25 `bootstrap/aws-oidc` or `ci/aws_plan`. Do not change the behavior of the three existing compositions.
- No registry/catalog refactor.
- Commit messages must not contain a `Co-authored-by` trailer. Do not rewrite historical commits to strip trailers.
- A task's validation command is the command on that task. `test_resource_registration_consistency.py` stays red from Task 4 until Task 9. The full CI command is required at Task 17, not after every earlier task.

**Gate structure:**

- **Gate A (Tasks 1–17):** deterministic and offline. No real Terraform, no real Checkov, no AWS, no GitHub, no OpenAI.
- **Gate B (Tasks 18–22):** real Terraform and real Checkov, credential-free, marked `real_tool`. No real AWS account.
- No Gate C/D/E.

**Files this plan creates:**

- `src/iac_agent/providers/aws/ecr/contract.py`
- `src/iac_agent/providers/aws/ecr/renderer.py`
- `terraform/modules/ecr/{main,variables,outputs,versions}.tf`
- `tests/unit/providers/aws/ecr/test_ecr_contract.py`
- `tests/unit/providers/aws/ecr/test_ecr_renderer.py`
- `tests/unit/policies/test_ecr_platform_policies.py`
- `tests/unit/graph/test_workflow_ecr.py`
- `tests/unit/evals/test_ecr_loader.py`
- `evals/datasets/ecr_golden.json`
- `evals/scenarios/ecr_loader.py`
- `evals/scenarios/ecr_runner.py`
- `evals/evaluators/ecr.py`
- `tests/integration/test_ecr_golden_evals.py`
- `tests/integration/test_ecr_renderer_terraform.py`
- `tests/integration/test_ecr_golden_real_tool_eval.py`
- `tests/integration/test_ecr_workflow_persistence.py`
- `docs/resources/ecr.md`

**Files this plan modifies:** the 20 dispatch sites and the prompt site in design §15, plus the 24 test/eval sites in design §16, plus `docs/roadmap.md` and `README.md`. `request.py` is not modified.

---

## Gate A — deterministic (offline, no real tools)

### Task 1: `EcrResourceSpec` contract

- [ ] **Files:** Create `src/iac_agent/providers/aws/ecr/contract.py`. Create `tests/unit/providers/aws/ecr/test_ecr_contract.py`.
- [ ] **Produces:** `EcrImageTagMutability`, `EcrEncryptionSpec`, `EcrResourceSpec` with `resource_type: Literal["ecr_repository"] = "ecr_repository"`.

**Tests, written first:**

- `EcrResourceSpec(name="orders")` succeeds. Defaults: `image_tag_mutability is EcrImageTagMutability.IMMUTABLE`, `scan_on_push is True`, `encryption.enabled is True`.
- `name="team/service"` succeeds. `name="a--b"` succeeds (`-+`). `name="a__b"` succeeds. `name="a.b"` succeeds. `name="1abc"` succeeds.
- Reject, with `ValidationError`: `""`, `"A"`, `"Orders"`, `"/team"`, `"team/"`, `"a..b"`, a 257-character string of `a`, a 1-character name, a name containing a space.
- `EcrEncryptionSpec(enabled=False)` and `EcrResourceSpec(name="orders", encryption=EcrEncryptionSpec(enabled=False))` raise `ValidationError` matching `encryption.enabled cannot be False`.
- `EcrEncryptionSpec` has no `kms_key_id` field (`"kms_key_id" not in EcrEncryptionSpec.model_fields`).
- `EcrResourceSpec` has no `force_delete` field and no lifecycle field.

**Minimum implementation:** copy the validator shape from `DynamoDBEncryptionSpec._enabled_must_be_true`. Name pattern, copied exactly and anchored:

```python
_ECR_NAME_PATTERN = re.compile(
    r"^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*$"
)
```

Length check is separate: `2 <= len(value) <= 256`.

**RED:** `pytest tests/unit/providers/aws/ecr/test_ecr_contract.py -v` fails because the module does not exist.
**GREEN:** the same command passes.
**Commit:** `feat(ecr): add EcrResourceSpec contract`
**Deterministic/offline.**

### Task 2: trusted ECR module

- [ ] **Files:** Create `terraform/modules/ecr/main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`.
- [ ] **Consumes:** the name regex and the AES256-only decision from Task 1. No Python import.

`main.tf` is exactly one managed resource:

```hcl
resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = var.scan_on_push
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = var.tags
}
```

No `force_delete`. No `kms_key`. No `aws_ecr_lifecycle_policy`. No `aws_ecr_repository_policy`.

`variables.tf`: `name` (string, same regex and length 2–256), `image_tag_mutability` (string, default `"IMMUTABLE"`, validation allows only `MUTABLE` or `IMMUTABLE`), `scan_on_push` (bool, default `true`), `tags` (`map(string)`, default `{}`). No `encryption_type` variable.

`outputs.tf`: `arn`, `repository_url`, `registry_id`, each taken from `aws_ecr_repository.this`.

`versions.tf`: `required_version = ">= 1.5.0"`, `aws` source `hashicorp/aws`, version `~> 6.0`. Same pin as `terraform/modules/dynamodb/versions.tf`.

**Validation:** `terraform fmt -check -recursive -diff terraform/modules/ecr`
**Commit:** `feat(terraform): add the trusted ECR repository module`
**Deterministic/offline.** This task does not run `terraform init` or `plan`.

### Task 3: `EcrTerraformCompositionRenderer`

- [ ] **Files:** Create `src/iac_agent/providers/aws/ecr/renderer.py`. Create `tests/unit/providers/aws/ecr/test_ecr_renderer.py`.
- [ ] **Consumes:** `EcrResourceSpec` from Task 1. `render_versions_tf`, `render_provider_block`, `hcl_string`, `hcl_bool`, `hcl_tags` from `iac_agent.providers.aws.terraform_render`.
- [ ] **Produces:** `EcrTerraformCompositionRenderer.render(spec, *, module_source: str) -> GeneratedTerraformComposition`. `DEFAULT_MODULE_SOURCE = "../../terraform/modules/ecr"`.

**Tests, written first:**

- Output files are `main.tf` and `versions.tf`.
- `main.tf` contains exactly one `module "ecr"` block and zero `resource "aws_ecr_repository"` blocks.
- The module block sets `name`, `image_tag_mutability`, and `scan_on_push` from the spec.
- The module block does not set `encryption_type`, `kms_key`, `force_delete`, or a lifecycle argument. Encryption is the module's hardcoded block, not a root-module input.
- `versions.tf` equals `render_versions_tf()`.
- Two renders of the same spec are byte-identical.
- A `MUTABLE` / `scan_on_push=False` spec renders those values, not the defaults.

**RED:** `pytest tests/unit/providers/aws/ecr/test_ecr_renderer.py -v` fails because the renderer module does not exist.
**GREEN:** the same command passes.
**Commit:** `feat(ecr): add EcrTerraformCompositionRenderer`
**Deterministic/offline.** Do not wire `AWSResourceRenderer` in this task.

### Task 4: `ResourceType.ECR` and `resource_type_of`

- [ ] **Files:** Modify `src/iac_agent/domain/resource.py`, `src/iac_agent/providers/aws/resource.py`, `tests/unit/domain/test_resource.py`, `tests/unit/providers/aws/test_resource_dispatch.py`.
- [ ] **Consumes:** `EcrResourceSpec` from Task 1.
- [ ] **Produces:** `ResourceType.ECR = "ecr"`. `AWSResourceSpec` includes `EcrResourceSpec`. `resource_type_of(EcrResourceSpec(...)) is ResourceType.ECR`.

Add the enum member. Widen the union. Add:

```python
case EcrResourceSpec():
    return ResourceType.ECR
```

before the `raise ValueError`. Update `test_resource_type_has_exactly_sqs_s3_dynamodb_lambda_and_api_gateway` so the expected set is those five values plus `"ecr"`. Rename the test to include `ecr` if the name would otherwise lie.

**RED:** the domain test fails because `ResourceType.ECR` does not exist.
**GREEN:** `pytest tests/unit/domain/test_resource.py tests/unit/providers/aws/test_resource_dispatch.py -v`
**Commit:** `feat(domain): add ResourceType.ECR`
**Known red:** `tests/unit/test_resource_registration_consistency.py` fails until Task 9. Do not "fix" it by deleting assertions.
**Deterministic/offline.**

### Task 5: wire `AWSResourceRenderer`

- [ ] **Files:** Modify `src/iac_agent/providers/aws/renderer.py`, `tests/unit/providers/aws/test_renderer_dispatch.py`.
- [ ] **Consumes:** `EcrTerraformCompositionRenderer` from Task 3 and the widened union from Task 4.
- [ ] **Produces:** constructor parameter `ecr_renderer: EcrTerraformCompositionRenderer | None = None`, defaulting to `EcrTerraformCompositionRenderer()`. New match arm:

```python
case EcrResourceSpec():
    return self._ecr_renderer.render(spec, module_source=module_source)
```

**Tests:** rendering an `EcrResourceSpec` returns a composition whose `main.tf` contains `module "ecr"`. An injected fake `ecr_renderer` is the object whose `render` is called. Existing SQS/S3/DynamoDB/Lambda/API Gateway dispatch tests stay green.

**RED:** `pytest tests/unit/providers/aws/test_renderer_dispatch.py -v` fails with `ValueError` for an `EcrResourceSpec`.
**GREEN:** the same command passes.
**Commit:** `feat(aws): dispatch EcrResourceSpec through AWSResourceRenderer`
**Deterministic/offline.** `request.py` stays unchanged. Its `case _` already calls `resource_type_of` and `AWSResourceRenderer`.

### Task 6: platform policies

- [ ] **Files:** Modify `src/iac_agent/policies/platform.py`. Create `tests/unit/policies/test_ecr_platform_policies.py`.
- [ ] **Consumes:** `EcrResourceSpec`, `EcrImageTagMutability` from Task 1. `ResourceType.ECR` from Task 4.
- [ ] **Produces:** the three policy-ID constants, a `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE[ResourceType.ECR]` tuple of those three IDs plus `TF_NO_DESTRUCTIVE_CHANGES`, and a `case EcrResourceSpec():` arm in `evaluate_platform_policies`.

Finding rules:

- `ECR_ENCRYPTION_REQUIRED`: PASS when `encryption.enabled` is true, severity HIGH, source `FindingSource.PLATFORM_POLICY`. BLOCK when false. Test the BLOCK branch with `EcrEncryptionSpec.model_construct(enabled=False)` inside `EcrResourceSpec.model_construct(...)`, the same bypass `tests/unit/policies/test_dynamodb_platform_policies.py` uses.
- `ECR_SCAN_ON_PUSH_RECOMMENDED`: PASS when `scan_on_push` is true, WARN when false.
- `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED`: PASS when mutability is `IMMUTABLE`, WARN when `MUTABLE`.

A secure-default spec plus a create-only `PlanSummary` yields exactly those three IDs plus `TF_NO_DESTRUCTIVE_CHANGES`, all PASS. `evaluate_platform_policies` still raises `ValueError` for an unknown spec type.

**RED:** `pytest tests/unit/policies/test_ecr_platform_policies.py -v` fails because the case arm does not exist.
**GREEN:** the same command passes.
**Commit:** `feat(policies): add ECR repository platform policies`
**Deterministic/offline.**

### Task 7: empty Checkov profile

- [ ] **Files:** Modify `src/iac_agent/security/checkov_profiles.py`, `tests/unit/security/test_checkov_profiles.py`.
- [ ] **Consumes:** `ResourceType.ECR` from Task 4.
- [ ] **Produces:** `_PROFILES_BY_RESOURCE_TYPE[ResourceType.ECR] = CheckovScanProfile(skipped_checks=())`.

**Test:** `checkov_profile_for(ResourceType.ECR).skipped_checks == ()`. Do not add a skip ID in this task. Existing profile tests stay green.

**RED:** `checkov_profile_for(ResourceType.ECR)` raises `ValueError`.
**GREEN:** `pytest tests/unit/security/test_checkov_profiles.py -v`
**Commit:** `feat(security): register an empty Checkov profile for ECR`
**Deterministic/offline.** Gate B Task 19 is the only task allowed to replace this tuple.

### Task 8: workflow registration entries

- [ ] **Files:** Modify `src/iac_agent/graph/workflow.py`. Create `tests/unit/graph/test_workflow_ecr.py`.
- [ ] **Consumes:** `ResourceType.ECR` from Task 4. The module directory from Task 2.
- [ ] **Produces:**

```python
ResourceType.ECR: _REPO_ROOT / "terraform" / "modules" / "ecr",
```

in `_DEFAULT_TRUSTED_MODULE_DIRS`, and

```python
ResourceType.ECR: "ECR",
```

in `_RESOURCE_KIND_DISPLAY_NAMES`.

**Tests:** both lookups return those values. `_resource_kind_of(EcrResourceSpec(name="orders")) == "ECR"`. `_pr_body` for an ECR state contains `Resource type: ecr` and `Resource: orders`, and does not contain a workspace path or raw plan JSON. No new `match` arm is added in `platform_policy`, `checkov_scan`, or `security_gate`. A unit test can show an `EcrResourceSpec` is not a `ServerlessWorkerSpec`, `ApiLambdaSpec`, or `ApiLambdaDynamoDbSpec`, so those grouped arms do not need widening.

**RED:** `KeyError` on `ResourceType.ECR` in the display-name dict.
**GREEN:** `pytest tests/unit/graph/test_workflow_ecr.py -v`
**Commit:** `feat(graph): register the ECR module directory and display name`
**Deterministic/offline.**

### Task 9: registration-consistency example

- [ ] **Files:** Modify `tests/unit/test_resource_registration_consistency.py`.
- [ ] **Consumes:** Tasks 1–8. This task adds no production code.
- [ ] **Produces:** `_EXAMPLE_SPECS[ResourceType.ECR] = EcrResourceSpec(name="orders")`.

**GREEN:** `pytest tests/unit/test_resource_registration_consistency.py -v` passes, including `set(_EXAMPLE_SPECS) == set(ResourceType)`, renderer dispatch, required policy IDs, Checkov lookup, on-disk module directory, and non-empty display name.
**Commit:** `test(ecr): cover ResourceType.ECR in registration consistency`
**Deterministic/offline.** This is the first task after which the registration-consistency file is green.

### Task 10: checkpoint allowlist

- [ ] **Files:** Modify `src/iac_agent/persistence/checkpoints.py`, `tests/unit/persistence/test_checkpoints_allowed_types.py`.
- [ ] **Consumes:** the three types from Task 1.
- [ ] **Produces:** these tuples, in this order, next to the other AWS contract entries:

```python
("iac_agent.providers.aws.ecr.contract", "EcrResourceSpec"),
("iac_agent.providers.aws.ecr.contract", "EcrImageTagMutability"),
("iac_agent.providers.aws.ecr.contract", "EcrEncryptionSpec"),
```

**Test:** build a real `EcrResourceSpec(name="team/service", tags={"owner": "platform"})`, round-trip it through `_build_serializer().dumps_typed` / `loads_typed`, and assert `type(recovered) is EcrResourceSpec` (not `isinstance` alone, and not `dict`). Assert recovered mutability, `scan_on_push`, and `encryption.enabled`.

**RED:** the recovered value is a `dict` or the serializer rejects the type. Record the actual RED exception or type in the commit message body if it differs from the dict degradation Batch 26 saw. Do not weaken the assertion to match a permissive result.
**GREEN:** `pytest tests/unit/persistence/test_checkpoints_allowed_types.py -v`
**Commit:** `fix(persistence): allow EcrResourceSpec in the checkpoint serializer`
**Deterministic/offline.** The fresh-process proof is Task 21.

### Task 11: fail-closed CLI label

- [ ] **Files:** Modify `src/iac_agent/cli/present.py`, `tests/unit/cli/test_present.py`.
- [ ] **Consumes:** `ResourceType` and `resource_type_of` from Task 4.
- [ ] **Produces:** `_STANDALONE_RESOURCE_LABELS` and a rewritten `_architecture_label`. Also an `EcrResourceSpec` branch in `_component_lines`.

```python
_STANDALONE_RESOURCE_LABELS: dict[ResourceType, str] = {
    ResourceType.SQS: "sqs",
    ResourceType.S3: "s3",
    ResourceType.DYNAMODB: "dynamodb",
    ResourceType.LAMBDA: "lambda",
    ResourceType.API_GATEWAY: "api_gateway",
    ResourceType.ECR: "ecr",
}

def _architecture_label(spec: IacRequestSpec) -> str:
    if isinstance(spec, ServerlessWorkerSpec):
        return "serverless_worker"
    if isinstance(spec, ApiLambdaDynamoDbSpec):
        return _API_LAMBDA_DYNAMODB_ARCHITECTURE_LABEL
    if isinstance(spec, ApiLambdaSpec):
        return "api_lambda"
    return _STANDALONE_RESOURCE_LABELS[resource_type_of(spec)]
```

There is no `return "s3"` left in this function.

`_component_lines` for `EcrResourceSpec` returns:

```python
[
    f"  repository: {spec.name}",
    f"  image_tag_mutability: {spec.image_tag_mutability.value}",
    f"  scan_on_push: {str(spec.scan_on_push).lower()}",
]
```

Other standalone specs still return `[]`. Do not convert `_component_lines` into a dict.

**Tests:**

- `test_every_resource_type_has_a_cli_architecture_label` iterates `ResourceType` and asserts membership in `_STANDALONE_RESOURCE_LABELS`.
- `_architecture_label(EcrResourceSpec(name="orders")) == "ecr"`.
- `_architecture_label(SQSResourceSpec(name="order-events")) == "sqs"`, and the same for DynamoDB, Lambda, and API Gateway. S3 remains `"s3"`.
- Existing composition labels are unchanged, including `"API Gateway + Lambda + DynamoDB"`.
- ECR component lines contain the repository name, `IMMUTABLE`, and `true`.

**RED:** before the edit, `_architecture_label(EcrResourceSpec(name="orders")) == "s3"`. Assert that RED fact in the new test, then make the edit.
**GREEN:** `pytest tests/unit/cli/test_present.py -v`
**Commit:** `fix(cli): fail closed when a standalone resource has no architecture label`
**Deterministic/offline.**

### Task 12: `Capability.CONTAINER_REGISTRY` and the resolver arm

- [ ] **Files:** Modify `src/iac_agent/intent/models.py`, `src/iac_agent/intent/resolver.py`, `tests/unit/intent/test_architecture_resolver.py`.
- [ ] **Consumes:** `EcrResourceSpec` from Task 1. `resolve_base_name` already in `resolver.py`.
- [ ] **Produces:** `Capability.CONTAINER_REGISTRY = "container_registry"`. `AwsServiceHint.ECR = "ecr"`. Update the `Capability` docstring from "Exactly these four members" to five members. Keep the sentence that `BACKGROUND_PROCESSING` was rejected. Add `_build_ecr_spec` and one new match arm immediately after the `OBJECT_STORAGE` arm:

```python
case WorkloadType.STORAGE if capabilities == frozenset({Capability.CONTAINER_REGISTRY}):
    return ResolvedArchitecture(
        request_spec=_build_ecr_spec(intent, request_id=request_id),
        matched_pattern="storage+container_registry",
    )
```

`_build_ecr_spec` uses `resolve_base_name(...)` as the repository name and leaves mutability, scan, and encryption at their defaults. It does not read `user_provided_hints`.

**Tests:**

- Parametrize `interaction_pattern` over `SYNCHRONOUS`, `ASYNCHRONOUS`, and `UNSPECIFIED`. Each resolves to `EcrResourceSpec` with `matched_pattern="storage+container_registry"`. None returns `ClarificationRequired`.
- `STORAGE + {CONTAINER_REGISTRY, OBJECT_STORAGE}` returns `UnsupportedArchitecture` with `UnsupportedReason.UNSUPPORTED_CAPABILITY`.
- `STORAGE + {CONTAINER_REGISTRY, PERSISTENCE}` does the same.
- The existing `test_storage_wrong_capability_set_returns_unsupported_capability` (`{PERSISTENCE}`) and `test_storage_object_storage_resolves_to_s3_spec_regardless_of_interaction_pattern` are not edited and still pass.
- A logical name hint `"Orders API"` resolves to a lowercase hyphenated name that `EcrResourceSpec` accepts.

**RED:** `STORAGE + {CONTAINER_REGISTRY}` cannot be constructed until the enum exists; after the enum and before the arm, resolution returns `UNSUPPORTED_CAPABILITY`.
**GREEN:** `pytest tests/unit/intent/test_architecture_resolver.py -v`
**Commit:** `feat(intent): resolve STORAGE+CONTAINER_REGISTRY to EcrResourceSpec`
**Deterministic/offline.**

### Task 13: interpreter prompt sentence

- [ ] **Files:** Modify `src/iac_agent/intent/adapters/openai.py`, `tests/unit/intent/adapters/test_openai_prompt_contract.py`.
- [ ] **Consumes:** the new vocabulary from Task 12. The prompt test reads the file with `ast` and does not import `openai`.
- [ ] **Produces:** `_PROMPT_VERSION = "4"`. Keep every existing instruction section. Add to `CAPABILITY ORTHOGONALITY`:

```text
container_registry means a private container image registry. Do not emit object_storage for a container registry. Do not emit container_registry for object or blob storage.
```

Add `ECR` to the parenthetical list of hintable services (`SQS, S3, DynamoDB, Lambda, API Gateway`). In the `workload_type` bullet, mention a container image registry beside object storage. Do not mention resolver allowlist rows, Terraform, or policy IDs.

**Tests:** change `test_prompt_version_is_3` to expect `"4"`. Add `test_prompt_distinguishes_container_registry_from_object_storage`, asserting both `container_registry` and `object_storage` appear and that the new "Do not emit object_storage for a container registry" sentence is present. Existing prompt-contract tests stay green without weakened assertions.

**RED:** `pytest tests/unit/intent/adapters/test_openai_prompt_contract.py::test_prompt_distinguishes_container_registry_from_object_storage -v` fails on the current prompt because `container_registry` is absent. Update the version assertion from `"3"` to `"4"` in the same commit as the constant.
**GREEN:** `pytest tests/unit/intent/adapters/test_openai_prompt_contract.py -v`
**Commit:** `feat(intent): tell the interpreter that a container registry is not object storage`
**Deterministic/offline.** Do not call OpenAI.

### Task 14: resolver golden scenarios

- [ ] **Files:** Modify `evals/datasets/architecture_intent_resolver_golden.json`, `tests/integration/test_architecture_intent_golden_evals.py`.
- [ ] **Consumes:** Task 12.
- [ ] **Produces:** two new scenarios. No existing scenario object is edited.

`storage_container_registry_resolves_to_ecr_repository`:

- input: `schema_version="1"`, `workload_type="storage"`, `interaction_pattern="unspecified"`, `capabilities=["container_registry"]`
- expected: `schema_valid=true`, `outcome="resolved"`, `matched_pattern="storage+container_registry"`, `resolved_type="EcrResourceSpec"`

`storage_container_registry_with_object_storage_unsupported_capability`:

- input capabilities: `["container_registry", "object_storage"]`, workload `storage`, interaction `unspecified`
- expected: `schema_valid=true`, `outcome="unsupported"`, `reason="unsupported_capability"`

Add both IDs to `_REQUIRED_SCENARIO_IDS`. Leave every existing ID in that set.

**RED:** before the resolver arm, the first scenario fails. After Task 12 it should already pass once the JSON exists; write the JSON and the required-ID edit together.
**GREEN:** `pytest tests/integration/test_architecture_intent_golden_evals.py -v`
**Commit:** `test(evals): expect STORAGE+CONTAINER_REGISTRY to resolve to ECR`
**Deterministic/offline.** This file is inside `pytest -m "not real_tool and not real_llm"`. Confirm the new scenarios do not carry a `real_llm` marker.

### Task 15: ECR golden dataset

- [ ] **Files:** Create `evals/datasets/ecr_golden.json`, `evals/scenarios/ecr_loader.py`, `evals/scenarios/ecr_runner.py`, `evals/evaluators/ecr.py`, `tests/unit/evals/test_ecr_loader.py`, `tests/integration/test_ecr_golden_evals.py`.
- [ ] **Consumes:** Task 1 and Task 6. Mirror the S3 loader/runner/evaluator split (`evals/scenarios/s3_loader.py`, `s3_runner.py`, `evals/evaluators/s3.py`) at ECR's smaller field set.
- [ ] **Produces:** nine scenarios, IDs exactly:

1. `basic_secure_repository` — `{"name": "orders"}`. Valid. Mutability `IMMUTABLE`, `scan_on_push` true, encryption enabled, overall security `pass`.
2. `namespaced_repository_name` — `{"name": "team/service"}`. Valid, security `pass`.
3. `scan_on_push_disabled_warns` — `scan_on_push: false`. Valid, overall security `warn`, policy `ECR_SCAN_ON_PUSH_RECOMMENDED`.
4. `mutable_tags_warn` — `image_tag_mutability: "MUTABLE"`. Valid, overall security `warn`, policy `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED`.
5. `uppercase_name_rejected` — `{"name": "Orders"}`. `valid: false`.
6. `empty_name_rejected` — `{"name": ""}`. `valid: false`.
7. `leading_slash_rejected` — `{"name": "/team"}`. `valid: false`.
8. `name_too_long_rejected` — 257 `a` characters. `valid: false`.
9. `invalid_character_rejected` — `{"name": "order events"}`. `valid: false`.

The loader test rejects a duplicate id and a missing required key, following `tests/unit/evals/test_api_lambda_dynamodb_loader.py`. The integration test runs the full dataset and asserts zero failures. It must not use `pytest.mark.real_tool`.

**RED:** `pytest tests/unit/evals/test_ecr_loader.py -v` fails because the loader does not exist.
**GREEN:** `pytest tests/unit/evals/test_ecr_loader.py tests/integration/test_ecr_golden_evals.py -v`
**Commit:** `feat(evals): add the ECR repository golden dataset`
**Deterministic/offline.**

### Task 16: documentation

- [ ] **Files:** Create `docs/resources/ecr.md`. Modify `docs/roadmap.md` and `README.md`.
- [ ] **Consumes:** Tasks 1–15. Checkov skips are still empty; say that explicitly and point at Task 19 for the empirical profile.

`docs/resources/ecr.md` covers: why ECR is a standalone resource, the contract fields, the name regex including the leading-digit choice, the three policy IDs, the module's single resource and hardcoded AES256, the non-goals (lifecycle, repository policy, KMS, public ECR, registry-level scanning), and the CLI label fix. Do not document a Checkov skip that has not been observed.

`docs/roadmap.md`: add a "Phase 2 — ECR (Batch 27)" section in the same shape as the DynamoDB section, listing the theoretical dispatch sites from design §15. Leave a sentence that the actual-versus-theoretical comparison is filled in by Task 22. In that same roadmap section, record the design §22 future pressure tests (KMS, CloudFront + S3 + OAC, SNS / EventBridge, Secrets Manager, ECS/Fargate + ECR, ALB / networking, RDS / Aurora) and Agent Observability / LLMOps (Langfuse) as documentation only. State that Langfuse is not Checkov, not a platform policy, and not AWS infrastructure monitoring. Do not add a Langfuse dependency.

`README.md`: add ECR to the supported-resource sentences and link `docs/resources/ecr.md`. Do not describe ECR as a composition.

**Validation:** read-through against Tasks 1–15. `ruff check src/iac_agent/providers/aws/ecr src/iac_agent/policies/platform.py src/iac_agent/intent/resolver.py src/iac_agent/cli/present.py`
**Commit:** `docs: document the ECR repository vertical slice`
**Deterministic/offline.**

### Task 17: Gate A closing validation

- [ ] **Files:** none, unless a failure forces a new fix commit. Do not amend earlier commits.
- [ ] **Objective:** prove Gate A did not leave a stale golden expectation or a missed registration.

Run, in this order:

```bash
ruff check .
terraform fmt -check -recursive -diff terraform/ tests/terraform/
pytest -m "not real_tool and not real_llm"
```

Expected: Ruff clean, Terraform fmt clean, pytest green. The pytest command is the `Tests` job in `.github/workflows/ci.yml`. Do not substitute `pytest tests/unit`.

If an existing architecture-intent scenario fails, stop and fix it in a new commit. Design §14 says none should fail; a failure means the closure inventory was wrong.

**Commit:** none when the three commands pass. A fix, if needed, is a new commit that names the failing test.
**Deterministic/offline.** Gate A is not complete until this task's three commands have been run and recorded.

---

## Gate B — credential-free real tools

Every Gate B test uses `pytest.mark.real_tool` and skips when the needed binary is absent, matching `tests/integration/test_s3_renderer_terraform.py`. Use `terraform_test_env` / `terraform_plan_env_overrides` from `tests/integration/conftest.py`. Placeholder credentials only (`AWS_ACCESS_KEY_ID=test`, `AWS_SECRET_ACCESS_KEY=test`), the same overrides `graph/workflow.py` already uses. Never a real account. Never `terraform apply`. Never `terraform destroy`.

### Task 18: real Terraform plan proof

- [ ] **Files:** Create `tests/integration/test_ecr_renderer_terraform.py`.
- [ ] **Consumes:** Task 2 and Task 3.
- [ ] **Objective:** `EcrTerraformCompositionRenderer` output, written into a temp workspace with the trusted module copied beside it, passes `terraform fmt`, `init`, `validate`, and `plan`.

Assert on `terraform show -json` after plan:

- exactly one resource change, type `aws_ecr_repository`, action create
- `image_tag_mutability` is `IMMUTABLE` for the secure default
- `image_scanning_configuration.scan_on_push` is true
- `encryption_configuration.encryption_type` is `AES256`
- no `kms_key`, no lifecycle policy, no repository policy in the planned resource addresses

**Leading digit:** a second plan (or the same test, second case) renders `name="1orders"`. Record the provider result in the test. If validate/plan rejects it, do not ignore it. Add a failing contract test and tighten `_ECR_NAME_PATTERN` in a follow-up commit in this task's series, and say so in `docs/resources/ecr.md`. If the provider accepts it, the regex decision stands; the test asserts the plan contains that name.

**RED:** the test fails before the module or renderer exists. After Gate A it should pass unless the provider schema disagrees with design §1.13.
**GREEN:** `pytest tests/integration/test_ecr_renderer_terraform.py -v`
**Commit:** `test(ecr): prove the ECR renderer plans with real Terraform`
**Credential-free real tool.**

### Task 19: empirical Checkov profile

- [ ] **Files:** Modify `src/iac_agent/security/checkov_profiles.py`, `tests/unit/security/test_checkov_profiles.py`, `docs/resources/ecr.md`.
- [ ] **Consumes:** a rendered secure-default workspace from the Task 18 technique.
- [ ] **Objective:** follow design §9 in order. Do not start from a guessed skip list.

1. Render the secure-default `EcrResourceSpec` with the real module.
2. Run the existing Checkov adapter with `CheckovScanProfile(skipped_checks=())`.
3. Copy every finding id and title into the commit message or into `docs/resources/ecr.md` before classifying.
4. Classify each finding as a genuine defect, an accepted architectural trade-off, or a false positive. One sentence of justification each. "Checkov failed" is not a justification.
5. Fix genuine defects in the module or renderer and re-scan. A customer-managed-KMS finding is an accepted trade-off only if it matches the closed AES256-only decision. Do not add a KMS key to silence it.
6. Freeze only the accepted ids into `_PROFILES_BY_RESOURCE_TYPE[ResourceType.ECR]`.
7. If the zero-skip scan is already clean, the frozen tuple stays `()` and the doc says that.

**Test:** `test_checkov_profiles.py` asserts the frozen tuple equals the classified ids, in order, and no other ids. The registration-consistency test still passes.

**Commit:** `feat(security): freeze the empirical Checkov profile for ECR`
**Credential-free real tool.** The unit test that pins the tuple is deterministic and stays in the Gate A command after this commit.

### Task 20: real-tool golden evaluation

- [ ] **Files:** Create `tests/integration/test_ecr_golden_real_tool_eval.py`.
- [ ] **Consumes:** the dataset from Task 15, the renderer, the module, the frozen profile from Task 19.
- [ ] **Objective:** mirror `tests/integration/test_s3_golden_real_tool_eval.py`. Run the valid secure-default golden scenario through real Terraform plan and real Checkov with the frozen profile. Assert the security gate passes and the planned resource is one `aws_ecr_repository`. Invalid-name scenarios are not sent to Terraform.

**GREEN:** `pytest tests/integration/test_ecr_golden_real_tool_eval.py -v`
**Commit:** `test(ecr): prove ECR golden scenarios against real Terraform and Checkov`
**Credential-free real tool.**

### Task 21: fresh-process durable HITL proof

- [ ] **Files:** Create `tests/integration/test_ecr_workflow_persistence.py`.
- [ ] **Consumes:** Task 10's allowlist, Task 8's workflow entries, Task 19's profile.
- [ ] **Objective:** mirror `tests/integration/test_s3_workflow_persistence.py`.

Flow: real `build_iac_workflow` with the real `AWSResourceRenderer`, real Terraform, real Checkov, SQLite checkpointer; interrupt at approval; close the saver; open a new saver and a newly compiled graph on the same database file; `get_state` with `workflow_config(request_id)`. Assert `type(recovered["resource_spec"]) is EcrResourceSpec` and `not isinstance(recovered["resource_spec"], dict)`. Resume with `ApprovalDecision.APPROVE` through source control using the existing fake source-control adapter. Do not call GitHub.

**RED:** if Task 10's tuples are incomplete, the recovered spec is a `dict`. That failure is the point of this test.
**GREEN:** `pytest tests/integration/test_ecr_workflow_persistence.py -v`
**Commit:** `test(ecr): prove EcrResourceSpec survives a fresh-process HITL resume`
**Credential-free real tool.**

### Task 22: actual-versus-theoretical closure note

- [ ] **Files:** Modify `docs/resources/ecr.md` and the Batch 27 section of `docs/roadmap.md`. No production code.
- [ ] **Objective:** record what implementation actually touched, next to design §15 and §16.

List:

- actual production files modified
- actual test/eval files modified
- which edits were a dict or enum entry, and which were new behavior (contract, renderer, label dict, prompt sentence)
- which omitted registrations the tests caught loudly, and whether the checkpoint allowlist or `_component_lines` would still have failed silently without their dedicated tests
- the frozen Checkov ids, or the statement that the zero-skip scan was clean
- the leading-digit provider result from Task 18

Do not start a registry refactor in this note. The Batch 28 conclusion stays "possibly justified but premature" unless the actual list shows a silent class the dedicated tests did not catch. If that happens, write the evidence and stop. Do not implement the registry.

**Validation:** `pytest -m "not real_tool and not real_llm"` once more, plus `ruff check .`, plus `terraform fmt -check -recursive -diff terraform/ tests/terraform/`. Then the Gate B files:

```bash
pytest tests/integration/test_ecr_renderer_terraform.py tests/integration/test_ecr_golden_real_tool_eval.py tests/integration/test_ecr_workflow_persistence.py -v
```

**Commit:** `docs: record Batch 27 actual dispatch sites against the theoretical inventory`
**Credential-free** for the doc commit. The Gate B pytest rerun needs the local Terraform and Checkov binaries.

---

## Plan self-review

**Spec coverage:**

| Design | Task |
|---|---|
| §2 contract, regex, encryption validator | 1 |
| §5 module, hardcoded AES256 | 2 |
| §6 renderer | 3, 5 |
| §3 `ResourceType.ECR`, not a composition | 4 |
| §7 policy IDs | 6 |
| §9 / §18 empty Checkov profile, then empirical freeze | 7, 19 |
| §11 workflow dicts, no new workflow match arm | 8 |
| §15 registration consistency | 9 |
| §10 checkpoint tuples and fresh-process proof | 10, 21 |
| §12 CLI dict, exhaustiveness test, component lines | 11 |
| §4 resolver arm, no clarification arm, fail-closed mixed sets | 12, 14 |
| §4 prompt sentence and version `"4"` | 13 |
| §13 nine golden scenarios | 15 |
| §14 CI command, Ruff, terraform fmt | 17, 22 |
| §16 test inventory | 1–15 and 18–21 |
| §19 non-goals | absent from every task; Task 1 asserts no `kms_key_id` / `force_delete` |
| §21 registry not implemented | 22 records evidence and does not refactor |
| §22 roadmap / Langfuse | Task 16 may name Langfuse only as future and out of scope; no task implements it |
| Leading-digit verification | 18 |

**Existing golden datasets whose expected outcomes do not change:** every current scenario in `architecture_intent_resolver_golden.json` and `architecture_intent_nl_golden.json`, plus the SQS, S3, DynamoDB, Lambda, and three composition datasets. Task 14 adds two resolver scenarios and does not edit the others. Task 17 runs the suite that would catch a stale expectation.

**Placeholder scan:** no task says TBD, "write tests for the above", or "similar to Task N" without naming the file and the assertion.

**Type consistency:** `EcrTerraformCompositionRenderer`, `EcrResourceSpec`, `EcrImageTagMutability`, `EcrEncryptionSpec`, `Capability.CONTAINER_REGISTRY`, `AwsServiceHint.ECR`, `ResourceType.ECR`, and the three policy IDs are the same names in every task.

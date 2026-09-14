# Deterministic Evals

## What a "deterministic eval" is, and how it differs from a unit test

Unit tests (under `tests/`) verify that individual pieces of code —
the SQS contract, the renderer, the plan analyzer, the policy engine,
the security gate — behave correctly in isolation. They are aimed at
*this codebase*.

Evals (under `evals/`) are versioned, product-facing behavioral
scenarios aimed at *the system's actual behavior end to end*: given a
natural-language-shaped SQS request, does the whole deterministic
pipeline (contract validation → Terraform rendering → security
evaluation) do what it is supposed to? Each scenario carries an
explicit **input** and an explicit **expected** outcome, versioned
together in a human-readable dataset file — not buried inside test
source code.

The relationship: **the test suite verifies the eval framework itself**
(the loader, the evaluators, the runner — see
`tests/unit/evals/` and `tests/unit/domain/test_evals.py`). **The eval
scenarios verify product behavior** (see
`evals/datasets/sqs_golden.json` and the evaluators in
`evals/evaluators/sqs.py`).

## Dataset location

`evals/datasets/sqs_golden.json` — a version-controlled JSON file
(`{"version": 1, "scenarios": [...]}`). It is plain data, not Python
code, so it can also be read by CI, reporting tools, or a future UI
without importing this project. It contains no secrets, account IDs,
company-specific terminology, or developer paths.

## Current SQS scenario coverage

Fourteen scenarios, in dataset order (the order the runner also reports
results in):

| Scenario ID | Proves |
|---|---|
| `basic_standard_queue` | A minimal valid standard queue with only a name, safe defaults everywhere else |
| `encrypted_queue_with_dlq` | SSE-KMS via an existing key reference, with the default DLQ still enabled |
| `fifo_queue` | A FIFO queue with a correctly-suffixed name |
| `invalid_fifo_name_combination` | `fifo=true` without a `.fifo` name is rejected, not silently rewritten |
| `invalid_message_retention` | A retention value below the AWS/contract minimum is rejected |
| `attempted_encryption_disable` | `encryption.enabled=false` is rejected at the Pydantic boundary, before any rendering/planning/security evaluation |
| `dlq_disabled_warn` | A disabled DLQ is a legitimate, non-blocking WARN outcome |
| `secure_default_queue_pass` | The representative secure-default configuration — also the one scenario exercised against the real Terraform/Checkov binaries (see below) |
| `boundary_numeric_values_valid` *(extra)* | Every numeric field at its inclusive minimum still constructs successfully |
| `invalid_queue_name_charset` *(extra)* | A disallowed character in the queue name is rejected |
| `derived_dlq_name_boundary_valid` *(Batch 12.5)* | A 76-character standard name is valid — its Terraform-derived `<name>-dlq` DLQ name lands at exactly the 80-character limit |
| `derived_dlq_name_too_long_rejected` *(Batch 12.5)* | A 77-character standard name is individually valid but is rejected because its derived DLQ name would be 81 characters |
| `long_primary_without_dlq_valid` *(Batch 12.5)* | The same 77-character name is valid once the DLQ is disabled — no DLQ name is ever derived |
| `fifo_derived_dlq_name_too_long_rejected` *(Batch 12.5)* | The FIFO mirror of `derived_dlq_name_too_long_rejected`: a 77-character `.fifo` name whose derived `<base>-dlq.fifo` name would be 81 characters |

Each scenario's `expected` block records: `valid`, and — only when
`valid` is `true` — `queue_name`, `fifo`, `dlq_enabled`,
`encryption_enabled`, `kms_key_id`, and `overall_security_status`
(`pass` / `warn` / `block`). An expected-invalid scenario records
nothing beyond `valid: false`, since no spec is ever constructed to
compare further fields against.

## Evaluators

Four deterministic evaluators run per scenario:

1. **`contract_validity`** — always runs first. Confirms construction
   succeeds/fails exactly as expected. Only a `pydantic.ValidationError`
   counts as the anticipated rejection; any other exception is an
   `ERROR`, never a silent `PASS`.
2. **`field_expectations`** — compares only the explicitly-expected
   fields (name, fifo, dlq.enabled, encryption.enabled, kms_key_id)
   against the constructed spec.
3. **`rendering_determinism`** — renders the same spec twice and
   requires byte-identical output.
4. **`security_status`** — runs `evaluate_platform_policies` and
   `evaluate_security_gate` (the same functions Batches 7-9 already
   built and proved) against a typed, create-only `PlanSummary` fixture
   and a fixed, explicitly-constructed clean `CheckovScanResult` —
   **not** the real Terraform or Checkov binaries — and compares the
   resulting `overall_status`.

`field_expectations`, `rendering_determinism`, and `security_status`
only run when a valid spec was actually constructed. For an
expected-invalid scenario (correctly rejected) there is nothing further
to render, plan, or evaluate security for, so those three evaluators
are simply not invoked for that scenario — not run-and-ignored.

## How to run the evals

```python
from evals.scenarios.runner import run_sqs_golden_evals, format_summary

suite = run_sqs_golden_evals()
print(format_summary(suite))
```

Or via pytest, which exercises the same runner:

```bash
python -m pytest tests/integration/test_sqs_golden_evals.py -v
```

## No paid API requirement

The entire deterministic suite above (`run_sqs_golden_evals` and every
test that calls it) requires **no** LLM API key, **no** network access,
and **no** AWS account — it is pure Python over the existing contract,
renderer, and security-evaluation code. This is verified by a dedicated
test that patches `subprocess.run` out entirely and confirms the full
suite still completes.

Exactly one additional test —
`tests/integration/test_sqs_golden_real_tool_eval.py` — is marked
separately as a **real-tool** eval: it takes the `secure_default_queue_pass`
scenario's own input from the golden dataset and runs it through the
real Terraform and Checkov binaries (skipped automatically if either
binary is not on `PATH`). This is optional evidence, not part of the
fast deterministic suite, and no other scenario is run this way.

## Future work (not implemented yet)

LLM-dependent evals — measuring intent-classification and
parameter-extraction accuracy by actually invoking a configured LLM
against each scenario's natural-language-shaped prompt — are planned
for a later phase, once natural-language intent extraction exists in
this project. They do not exist yet, and nothing in this batch depends
on or anticipates a specific LLM provider.

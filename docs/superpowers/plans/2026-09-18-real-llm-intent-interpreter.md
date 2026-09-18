# Real LLM Intent Interpreter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first real `IntentInterpreterPort` adapter
(OpenAI) behind a multi-provider-ready composition boundary, plus the
provider-neutral Layer 2 natural-language eval layer — without ever
letting the LLM become authoritative over architecture, Terraform,
IAM, security, or GitHub, and without ordinary CI ever making a real
model call.

**Architecture:** `IAC_AGENT_LLM_PROVIDER`/`IAC_AGENT_LLM_MODEL` config
→ one composition-boundary dispatch (`create_intent_interpreter`) →
`OpenAIIntentInterpreter` (implements the unchanged
`IntentInterpreterPort`) → `parse_intent_payload` (unchanged,
authoritative) → `ArchitectureIntent` (unchanged) →
`ArchitectureResolver` (unchanged, deterministic) → existing pipeline.

**Tech Stack:** Python 3.12, Pydantic, the `openai` SDK (new, optional
dependency, this batch's only new runtime dependency).

**Spec:** docs/superpowers/specs/2026-09-18-real-llm-intent-interpreter-design.md

## Global Constraints

Carried forward verbatim from the approved design and the 17
non-negotiable invariants — none of these are open for
reinterpretation during implementation:

1. **The LLM cannot construct `IacRequestSpec`, generate authoritative
   Terraform/IAM, make `SecurityGate`/HITL decisions, execute tools, run
   `terraform apply`/`destroy`, or mutate GitHub.** No task below touches
   `iac_agent.graph`, `iac_agent.execution`, `iac_agent.security`,
   `iac_agent.git`, or `iac_agent.policies`.
2. **`ArchitectureResolver`, `parse_intent_payload`, `ArchitectureIntent`,
   and `IntentInterpreterPort` are unchanged.** Every task only *adds*
   new files/functions around them.
3. **`user_provided_hints` and `confidence` remain non-authoritative** —
   unchanged resolver behavior; Layer 2 never grades `confidence` for
   PASS/FAIL.
4. **Raw prompts and raw provider responses are never persisted or
   logged**, by the adapter or anywhere else this batch touches.
5. **Ordinary CI (`Quality`, `Tests`, `Tool Validation`) makes zero real
   LLM calls and requires zero `OPENAI_API_KEY`.** `.github/workflows/ci.yml`
   is not modified by any task in this plan.
6. **No automatic provider fallback.** One configured provider per
   execution; an unrecognized provider fails closed at configuration
   time.
7. **No provider-specific type, object, or name leaks past the adapter
   boundary** — not into `ArchitectureIntent`, not into
   `IntentResolutionService`, not into `WorkflowState`.
8. **Bare `pip install -e .` never installs the `openai` SDK.** Only
   `pip install -e ".[openai]"` does. This requires the `openai` import
   inside `iac_agent.app.composition` to be **lazy** (deferred into the
   function body, never at module scope) — getting this wrong would
   silently break the optional-dependency guarantee for every existing
   Terraform-pipeline user. Task 6 includes a dedicated test for this.
9. **Retries: max 2 attempts total (1 retry), retryable categories only**
   (`IntentProviderUnavailableError`, `IntentProviderTimeoutError`).
   `IntentProviderRefusalError` and any `parse_intent_payload` failure
   are never retried. No prompt-repair loop, no self-correction, no
   cross-provider fallback.
10. **No new domain error** — the existing five-member
    `IntentInterpreterError` hierarchy is sufficient (per the approved
    design's own mapping table); no task introduces a sixth.
11. **Scope discipline.** This plan implements OpenAI only. It never
    creates an Anthropic or Bedrock adapter, a failover mechanism,
    multi-provider voting, LLM-as-judge, an agent loop, tool-calling, a
    UI, Terraform/IAM generation, or any CI/branch-protection change.
12. **Git discipline.** Continue on the existing branch
    `docs/batch23-real-llm-intent-design` for Tasks 1–2 (pure
    configuration/dependency-declaration, no adapter code yet — see
    "Branch strategy" below for exactly when and how to move to a
    dedicated implementation branch). Commit frequently with the exact
    messages given per task. Never force-push, amend, or rewrite
    history. No `Co-Authored-By` trailer in any commit this plan
    proposes. Never push without a separate, explicit instruction to do
    so.
13. **The real-model checkpoint (Task 10) is a hard stop.** No task
    before it may call OpenAI for real, install nothing beyond the
    `openai` package itself, or require `OPENAI_API_KEY` to be set.
    Task 11 (the first real call) is **not** auto-executed by following
    this plan — it requires a separate, explicit human authorization
    after the checkpoint report.

---

## Repository verification snapshot (re-confirmed at design commit `c98d82e`)

- `IntentInterpreterPort.interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent`
  — unchanged (`src/iac_agent/intent/port.py`).
- `parse_intent_payload(raw_payload: Mapping[str, Any]) -> ArchitectureIntent`
  — unchanged, same file: schema-version gate → `model_validate` →
  `IntentValidationError`.
- `IntentInterpreterError` hierarchy — unchanged, five subtypes:
  `IntentSchemaVersionUnsupportedError`, `IntentValidationError`,
  `IntentProviderUnavailableError`, `IntentProviderTimeoutError`,
  `IntentProviderRefusalError`.
- `ArchitectureIntent` fields — unchanged (`src/iac_agent/intent/models.py`):
  `schema_version`, `workload_type`, `interaction_pattern`,
  `capabilities`, `logical_name_hint`, `user_provided_hints`,
  `assumptions`, `unresolved_questions`, `confidence`.
- `ArchitectureResolver.resolve(*, intent, request_id) -> ResolutionResult`
  — unchanged, three-row closed allowlist.
- `IntentResolutionService.submit(*, request_id, natural_language_request) -> IntentSubmissionResult`
  — unchanged.
- `iac_agent.app.config` — existing pattern to extend:
  `ApplicationConfig` (non-secret dataclass) + `load_application_config_from_env`
  (env-reading, `MissingConfigurationError` on any missing required
  value) + `load_github_token_from_env` (`SecretStr`, loaded separately
  from config, `_ENV_GITHUB_TOKEN = "GITHUB_TOKEN"` constant pattern).
- `iac_agent.app.composition` — existing pattern to extend:
  `open_application` is the **only** place real adapters are
  constructed; it accepts an injectable transport
  (`github_transport: HttpTransport | None = None`) purely so tests can
  inject a fake through the same production composition path — the
  exact seam `OpenAIIntentInterpreter`'s own client parameter will
  mirror.
- `pyproject.toml` — one extras group today (`dev`); no `openai`,
  `anthropic`, or `boto3` anywhere; `requires-python = ">=3.12,<3.13"`.
- `real_llm` marker + `tests/integration/test_architecture_intent_nl_real_model_eval.py`
  — double-guarded, zero real calls today; this is the file Task 9
  activates.
- Existing eval triple convention (`evals/{datasets,evaluators,scenarios}/`)
  — mirrored exactly by Tasks 7–8's new
  `architecture_intent_nl_{golden.json,evaluators,loader,runner}` files,
  and `evals.scenarios.runner.format_summary` is reused directly rather
  than reimplemented, per the existing generic-`title`-kwarg pattern.
- Fakes-in-tests convention (`iac_agent.intent`) — every fake this plan
  introduces (`FakeIntentInterpreter` variants, a fake OpenAI client
  object) lives inside the test file that uses it, never importable
  from `src/`.

## Branch strategy

Tasks 1–2 (pure configuration and dependency *declaration*, no adapter
code) continue on the existing `docs/batch23-real-llm-intent-design`
branch, exactly mirroring how Batch 21's plan and implementation
commits shared one branch. Before Task 3 (the first task that adds
actual adapter code and requires `pip install -e ".[openai]"` locally),
verify the branch is still based on the current verified `main`
(`git merge-base --is-ancestor <main SHA> HEAD`) — if `main` has
legitimately advanced since this plan was written, that is expected and
not a blocker; only an *unexpected* divergence (this branch missing a
commit that should be its ancestor) is a STOP condition. No new branch
or worktree is needed unless the implementer is resuming this plan in a
new session after `main` has advanced significantly — in that case,
rebase is explicitly **not** used (no history rewriting); instead merge
`main` into the branch, or start a fresh branch from `main` and
`git cherry-pick` this plan's already-completed task commits in order.

---

## Task ordering

| # | Task | Scope letter(s) |
|---|---|---|
| 1 | Provider-neutral configuration | A |
| 2 | Optional OpenAI dependency declaration | C |
| 3 | OpenAI adapter: structured-output request/response boundary | D, E, F |
| 4 | Error normalization + bounded retry/timeout | G, H |
| 5 | Privacy-safe telemetry | I |
| 6 | Composition boundary + multi-provider isolation regression | B, multi-provider test |
| 7 | Layer 2 dataset | K |
| 8 | Layer 2 evaluator + runner | L, M |
| 9 | Activate the `real_llm` integration skeleton | N |
| 10 | Documentation + deterministic validation + **human checkpoint** | O, P |
| 11 *(gated, not auto-executed)* | First real `pytest -m real_llm` run, triage, report | — |

---

## Task 1 — Provider-neutral configuration

**Files**
- Modify: `src/iac_agent/app/config.py`
- Create: `tests/unit/app/test_intent_interpreter_config.py`

**Interfaces**
- Produces: `IntentInterpreterProvider(StrEnum)` = `OPENAI = "openai"`
  only (commented-out `ANTHROPIC`/`BEDROCK` members, not real members
  yet); `IntentInterpreterConfig(frozen dataclass)` =
  `(provider: IntentInterpreterProvider, model: str)`;
  `load_intent_interpreter_config_from_env(env: Mapping[str,str]|None=None) -> IntentInterpreterConfig`;
  `load_openai_api_key_from_env(env=None) -> SecretStr`.
- Consumes: `os`, `enum.StrEnum`, existing `MissingConfigurationError`,
  existing `_ENV_*` constant-naming convention.

**New env var constants:** `_ENV_LLM_PROVIDER = "IAC_AGENT_LLM_PROVIDER"`,
`_ENV_LLM_MODEL = "IAC_AGENT_LLM_MODEL"`, `_ENV_OPENAI_API_KEY = "OPENAI_API_KEY"`.

**Steps**

- [ ] Write `tests/unit/app/test_intent_interpreter_config.py` with:
  1. `test_load_config_with_valid_openai_provider_and_model`
  2. `test_load_config_missing_provider_raises_missing_configuration_error`
  3. `test_load_config_missing_model_raises_missing_configuration_error`
  4. `test_load_config_unknown_provider_string_raises_missing_configuration_error`
  5. `test_load_config_never_reads_openai_api_key` (constructs env with
     `OPENAI_API_KEY` set but `IAC_AGENT_LLM_PROVIDER`/`_MODEL` unset;
     asserts `MissingConfigurationError`, proving the key is never
     treated as a provider/model substitute)
  6. `test_intent_interpreter_config_is_frozen`
  7. `test_load_openai_api_key_from_env_returns_secret_str`
  8. `test_load_openai_api_key_from_env_missing_raises_missing_configuration_error`
  9. `test_load_openai_api_key_from_env_never_appears_in_repr` (assert
     the loaded `SecretStr`'s `repr()`/`str()` never contains the raw
     key value)
- [ ] Run: `.venv/bin/python -m pytest tests/unit/app/test_intent_interpreter_config.py -v`
      Expected failure: `ImportError`/`AttributeError` — the new names
      don't exist yet.
- [ ] Implement `IntentInterpreterProvider`, `IntentInterpreterConfig`,
      `load_intent_interpreter_config_from_env`,
      `load_openai_api_key_from_env` in `src/iac_agent/app/config.py`,
      exactly mirroring `ApplicationConfig`/`load_application_config_from_env`/
      `load_github_token_from_env`'s existing shape and docstring style.
- [ ] Run the same command again. Expected: `9 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q` — expected: no
      regressions.
- [ ] Run: `.venv/bin/ruff check src/iac_agent/app/config.py tests/unit/app/test_intent_interpreter_config.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(app): add provider-neutral LLM interpreter configuration
      ```

---

## Task 2 — Optional OpenAI dependency declaration

**Files**
- Modify: `pyproject.toml`

**Steps**

- [ ] Add, without touching `[project.dependencies]` or the existing
      `dev` extras group:
      ```toml
      [project.optional-dependencies]
      dev = [
          "pytest>=8.0",
          "ruff>=0.6",
      ]
      openai = [
          "openai>=<verify current stable 1.x floor at implementation time>,<2",
      ]
      ```
      Verify the actual current stable `openai` package version at
      implementation time (`pip index versions openai` or the package's
      PyPI page) rather than guessing a floor now — this design was
      written before implementation and must not silently assume a
      version that may already be outdated.
- [ ] Confirm bare install is unaffected: `.venv/bin/pip install -e . --dry-run 2>&1 | grep -i openai`
      — expected: no output (the bare install path never even
      considers the new extra).
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat: add optional openai extras group
      ```

---

## Task 3 — OpenAI adapter: structured-output request/response boundary

**Files**
- Create: `src/iac_agent/intent/adapters/__init__.py` (empty)
- Create: `src/iac_agent/intent/adapters/openai.py`
- Create: `tests/unit/intent/adapters/__init__.py` (empty)
- Create: `tests/unit/intent/adapters/test_openai_adapter.py`

**Interfaces**
- Produces: `OpenAIIntentInterpreter` implementing
  `IntentInterpreterPort` exactly:
  ```python
  class OpenAIIntentInterpreter:
      def __init__(
          self, *, model: str, api_key: SecretStr, client: Any | None = None
      ) -> None: ...

      def interpret(
          self, *, natural_language_request: str, request_id: str
      ) -> ArchitectureIntent: ...
  ```
  `client` mirrors `open_application`'s own `github_transport: HttpTransport | None = None`
  seam exactly: `None` constructs a real `openai.OpenAI(api_key=...)`;
  tests inject a fake/stub object exposing only the one method the
  adapter actually calls — no real network, no real key, ever required
  for these tests.
- Consumes: `iac_agent.intent.port.{parse_intent_payload, IntentInterpreterError subtypes}`,
  `iac_agent.intent.models.ArchitectureIntent` (for typing only), the
  `openai` package (imported **inside this module only** — this module
  is never imported at package-import time by anything that doesn't
  need it; see Task 6 for the composition-side lazy-import proof).

**Design points to implement exactly as specified (not re-derived):**
- `_PROMPT_VERSION = "1"` module constant, recorded by every call
  (consumed by Task 5's telemetry).
- The prompt contract instructs: extract semantic intent only
  (`workload_type`/`interaction_pattern`/`capabilities`/
  `logical_name_hint`/`user_provided_hints`/`assumptions`/
  `unresolved_questions`/`confidence`); explicitly forbidden from
  writing Terraform, choosing IAM, judging security, calling tools,
  browsing, mutating GitHub, or executing `apply`/`destroy`; the
  resolver's exact allowlist rows are never disclosed; the request text
  is described as *data to interpret*, never *instructions to follow*.
- The adapter's request-time JSON schema **never includes
  `schema_version`** as a model-producible field — the adapter injects
  `"schema_version": "1"` into the raw payload dict itself, after
  receiving the model's structured response and before calling
  `parse_intent_payload`.
- `logical_name_hint` and `confidence` are declared nullable in the
  request schema; a returned `null` passes straight into the raw
  payload dict unchanged (no adapter-side translation needed —
  `ArchitectureIntent`'s own `Optional` fields already treat an
  explicit `None` identically to their default).
- `user_provided_hints`, `assumptions`, `unresolved_questions` are
  declared as plain (non-nullable) arrays in the request schema, empty
  array being the "nothing here" value.
- Every raw payload the adapter constructs — valid or malformed —
  passes through `parse_intent_payload` before this method returns;
  there is no code path that constructs an `ArchitectureIntent` any
  other way.

**Steps**

- [ ] Write `tests/unit/intent/adapters/test_openai_adapter.py` with a
      locally defined `FakeOpenAIClient` (constructor takes a canned
      response object or an exception to raise, exposing only the one
      method `OpenAIIntentInterpreter` actually calls) and:
  1. `test_successful_response_produces_valid_architecture_intent`
  2. `test_adapter_injects_schema_version_not_the_model`
  3. `test_null_logical_name_hint_passes_through_as_none`
  4. `test_null_confidence_passes_through_as_none`
  5. `test_empty_arrays_for_hints_assumptions_unresolved_questions_are_valid`
  6. `test_malformed_response_raises_intent_validation_error` (fake
     client returns a payload missing a required field; assert it
     reaches `parse_intent_payload` and fails there, not inside the
     adapter with an unrelated exception)
  7. `test_unknown_capability_in_response_raises_intent_validation_error`
  8. `test_provider_specific_response_object_never_returned_or_leaked`
     (assert the method's return value is exactly an `ArchitectureIntent`
     instance — `type(result) is ArchitectureIntent` — never the raw
     SDK response object or a subclass)
- [ ] Run: `.venv/bin/python -m pytest tests/unit/intent/adapters/test_openai_adapter.py -v`
      Expected failure: `ModuleNotFoundError: No module named 'iac_agent.intent.adapters'`.
- [ ] `pip install -e ".[openai]"` locally (implementer's own dev
      environment — this is implementation-time tooling setup, not a
      change to what a bare install requires).
- [ ] Implement `src/iac_agent/intent/adapters/__init__.py` (empty) and
      `src/iac_agent/intent/adapters/openai.py` exactly per the design
      points above.
- [ ] Run the same test command again. Expected: `8 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q` — expected: no
      regressions (this also proves the new adapter package doesn't
      break collection for anyone without `openai` installed, since
      these tests only run with it installed in this dev environment —
      Task 6 adds the specific "importable without `openai`" proof for
      the *rest* of the codebase).
- [ ] Run: `.venv/bin/ruff check src/iac_agent/intent/adapters/ tests/unit/intent/adapters/`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(intent): add OpenAI structured-output intent interpreter adapter
      ```

---

## Task 4 — Error normalization + bounded retry/timeout

**Files**
- Modify: `src/iac_agent/intent/adapters/openai.py`
- Modify: `tests/unit/intent/adapters/test_openai_adapter.py`

**Interfaces**
- Extends `OpenAIIntentInterpreter.interpret` with the exact mapping
  table from the approved design (§6): connection failure / rate limit
  → `IntentProviderUnavailableError` (retryable); timeout →
  `IntentProviderTimeoutError` (retryable); the response's own
  `refusal` field set → `IntentProviderRefusalError` (never retried);
  any other malformed payload → falls through to `parse_intent_payload`
  → `IntentValidationError` (never retried); bad/revoked key discovered
  at request time → `IntentProviderUnavailableError` (never retried —
  a per-process retry cannot fix a bad key). **Missing `OPENAI_API_KEY`
  is never reached by this method at all** — it fails at
  `load_openai_api_key_from_env` (Task 1), before `create_intent_interpreter`
  (Task 6) can even construct this adapter.
- Retry policy: exactly 1 retry (2 attempts total) for the two
  retryable categories only, a short fixed backoff (implementation
  chooses an exact seconds value, documented), one overall per-call
  timeout (proposed default 30s, passed to the underlying client,
  configurable via an adapter constructor parameter with that default —
  never silently inherited from an SDK default).

**Steps**

- [ ] Add to `tests/unit/intent/adapters/test_openai_adapter.py`
      (`FakeOpenAIClient` extended to support "raise on first N calls,
      succeed after"):
  1. `test_connection_failure_raises_intent_provider_unavailable_error`
  2. `test_rate_limit_raises_intent_provider_unavailable_error`
  3. `test_timeout_raises_intent_provider_timeout_error`
  4. `test_refusal_field_raises_intent_provider_refusal_error`
  5. `test_authentication_error_at_request_time_raises_intent_provider_unavailable_error`
  6. `test_no_provider_sdk_exception_escapes_interpret` (parametrized
     over every raw SDK exception type used above; assert only
     `IntentInterpreterError` subtypes are ever raised out of
     `interpret`)
  7. `test_connection_failure_retries_exactly_once_then_succeeds`
     (fake client fails once, succeeds on the second call; assert
     exactly 2 calls were made and a valid `ArchitectureIntent` is
     returned)
  8. `test_connection_failure_retries_exactly_once_then_still_fails`
     (fake client always fails; assert exactly 2 calls were made, then
     `IntentProviderUnavailableError` propagates)
  9. `test_refusal_is_never_retried` (fake client set to fail-then-succeed,
     but the first response is a refusal; assert exactly 1 call was
     made — the retry budget is never spent on a non-retryable category)
  10. `test_malformed_payload_is_never_retried` (same shape, first
      response malformed; assert exactly 1 call was made)
  11. `test_no_automatic_fallback_to_another_provider` (a purely
      structural assertion: `OpenAIIntentInterpreter` has no
      constructor parameter or internal reference naming a second
      provider at all — grep-style check against the module's own
      source, mirroring the mechanical-proof style already used in
      `test_non_authoritative_metadata.py`)
- [ ] Run: `.venv/bin/python -m pytest tests/unit/intent/adapters/test_openai_adapter.py -v`
      Expected failure: the 11 new tests fail (retry/error-mapping
      logic doesn't exist yet); the 8 from Task 3 still pass.
- [ ] Implement the error mapping and retry/timeout logic.
- [ ] Run the same command again. Expected: `19 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q`
- [ ] Run: `.venv/bin/ruff check src/iac_agent/intent/adapters/openai.py tests/unit/intent/adapters/test_openai_adapter.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(intent): map OpenAI failures to typed interpreter errors with bounded retry
      ```

---

## Task 5 — Privacy-safe telemetry

**Files**
- Modify: `src/iac_agent/intent/adapters/openai.py`
- Modify: `tests/unit/intent/adapters/test_openai_adapter.py`

**Interfaces**
- The adapter emits exactly one `logging.getLogger("iac_agent.intent.adapters.openai")`
  record per `interpret()` call (stdlib `logging` — no new dependency,
  no existing repo-wide logging convention to conflict with; this is
  the first one, deliberately minimal), carrying only: `request_id`,
  `provider="openai"`, `model`, `prompt_version`, `latency_ms`,
  `attempt_count`, `outcome_category` (one of
  `schema_valid`/`validation_error`/`timeout`/`unavailable`/`refusal`),
  and token counts when the SDK response exposes them. **Never** the
  raw `natural_language_request`, the raw response body, or the API
  key.

**Steps**

- [ ] Add to `tests/unit/intent/adapters/test_openai_adapter.py` (using
      pytest's `caplog` fixture):
  1. `test_successful_call_logs_only_safe_metadata_fields`
  2. `test_log_record_never_contains_raw_natural_language_request`
  3. `test_log_record_never_contains_raw_response_body`
  4. `test_log_record_never_contains_api_key_value`
  5. `test_failure_call_logs_outcome_category_matching_the_raised_error`
- [ ] Run: `.venv/bin/python -m pytest tests/unit/intent/adapters/test_openai_adapter.py -v`
      Expected failure: the 5 new tests fail (no logging exists yet).
- [ ] Implement the logging call.
- [ ] Run the same command again. Expected: `24 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q`
- [ ] Run: `.venv/bin/ruff check src/iac_agent/intent/adapters/openai.py tests/unit/intent/adapters/test_openai_adapter.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(intent): add privacy-safe metadata-only telemetry to the OpenAI adapter
      ```

---

## Task 6 — Composition boundary + multi-provider isolation regression

**Files**
- Modify: `src/iac_agent/app/composition.py`
- Create: `tests/unit/app/test_intent_interpreter_composition.py`
- Create: `tests/unit/intent/test_multi_provider_boundary_isolation.py`

**Interfaces**
- Produces:
  ```python
  def create_intent_interpreter(
      config: IntentInterpreterConfig, *, api_key: SecretStr
  ) -> IntentInterpreterPort:
      match config.provider:
          case IntentInterpreterProvider.OPENAI:
              from iac_agent.intent.adapters.openai import OpenAIIntentInterpreter
              return OpenAIIntentInterpreter(model=config.model, api_key=api_key)
  ```
  The `from iac_agent.intent.adapters.openai import ...` is **inside the
  function**, not at module scope — this is Global Constraint 8's
  concrete implementation and the whole reason `iac_agent.app.composition`
  (imported unconditionally by every Terraform-pipeline user via
  `open_application`) never requires `openai` to be installed.
- This is the **only** place in `src/` that ever matches on
  `config.provider`/`IntentInterpreterProvider` — verified mechanically
  (see below), not just by convention.

**Steps**

- [ ] Write `tests/unit/app/test_intent_interpreter_composition.py` with:
  1. `test_create_intent_interpreter_openai_returns_openai_adapter_instance`
  2. `test_create_intent_interpreter_openai_returns_something_satisfying_the_port`
     (duck-type check: has an `interpret` callable with the right
     keyword-only parameters — no `isinstance`/`runtime_checkable`
     precedent exists in this codebase for ports, matching
     `SourceControlPort`'s own convention of never being
     `@runtime_checkable`)
- [ ] Write `tests/unit/intent/test_multi_provider_boundary_isolation.py`
      with (reusing the `ast`-based import-inspection helper pattern
      already established in `test_trust_boundary_isolation.py`):
  1. `test_architecture_intent_has_no_provider_model_or_credential_field`
     (introspect `ArchitectureIntent.model_fields.keys()`, assert none
     of `provider`/`model`/`api_key`/`credential` appear)
  2. `test_architecture_resolver_module_never_imports_openai_or_provider_enum`
  3. `test_intent_resolution_service_module_never_imports_openai_or_provider_enum`
  4. `test_composition_module_imports_openai_adapter_only_inside_a_function`
     (parse `iac_agent.app.composition`'s AST; walk only
     module-level — i.e. direct children of the `Module` node — `Import`/
     `ImportFrom` statements; assert none reference
     `iac_agent.intent.adapters.openai` or `openai`; separately assert
     the string `iac_agent.intent.adapters.openai` **does** appear
     somewhere in the file, proving the import exists but is deferred,
     not simply absent)
  5. `test_exactly_one_match_on_intent_interpreter_provider_exists_in_src`
     (walk every `.py` file under `src/`, count `ast.Match` nodes whose
     subject references `IntentInterpreterProvider` or `config.provider`;
     assert the count is exactly 1, located in
     `iac_agent/app/composition.py`)
- [ ] Run: `.venv/bin/python -m pytest tests/unit/app/test_intent_interpreter_composition.py tests/unit/intent/test_multi_provider_boundary_isolation.py -v`
      Expected failure: `create_intent_interpreter` doesn't exist yet;
      isolation tests 1–3 pass immediately (nothing to violate yet),
      tests 4–5 fail (nothing to find).
- [ ] Implement `create_intent_interpreter` in
      `src/iac_agent/app/composition.py` exactly as specified.
- [ ] Run the same command again. Expected: `7 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q`
- [ ] **Explicitly verify the lazy-import guarantee end to end:** in a
      throwaway shell with `openai` **not** installed (e.g. a fresh venv
      built only from `pip install -e .`, no `[openai]` extra), run
      `python -c "import iac_agent.app.composition; print('OK')"` —
      expected: `OK`, no `ModuleNotFoundError`. This is the one
      end-to-end proof no unit test alone can substitute for.
- [ ] Run: `.venv/bin/ruff check src/iac_agent/app/composition.py tests/unit/app/test_intent_interpreter_composition.py tests/unit/intent/test_multi_provider_boundary_isolation.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(app): add provider composition boundary and multi-provider isolation proofs
      ```

---

## Task 7 — Layer 2 dataset

**Files**
- Create: `evals/datasets/architecture_intent_nl_golden.json`

**Content:** ~24 scenarios exactly as enumerated in the approved
design §10 — `case1_sync_api_{en,es}` through `case9_irrelevant_non_iac_{en,es}`
(18), `case10_prompt_injection_ignore_instructions` through
`case14_request_terraform_apply` (5), `case15_paraphrase_of_case1`,
`case16_mixed_es_en`, `case17_harmless_noise`. Each scenario:
`{id, description, natural_language_request, expected}`, where
`expected` never contains a provider-specific value — only
`schema_valid`, and (when true) `workload_type`, `interaction_pattern`,
`capabilities`, optionally `user_provided_hints` (case 5 pair only),
`unresolved_questions_expected: bool`, and
`forbidden_top_level_keys_absent: true` (always).

**Steps**

- [ ] Write the dataset JSON with exactly the 24 scenario ids above,
      each with a genuinely distinct, natural-sounding request string
      in the correct language and semantically-honest `expected` block
      matching what the approved design specifies each case should
      mean (e.g. `case8_unsupported_request_en` describes an API
      needing relational persistence, `expected.schema_valid=true`,
      no `outcome`/architecture fields asserted here since Layer 2
      grades the *interpreter's* output, not the resolver's — resolver
      re-verification is Task 8's job, not the dataset's).
- [ ] Validate the JSON is well-formed:
      `.venv/bin/python -c "import json; d = json.load(open('evals/datasets/architecture_intent_nl_golden.json')); assert len(d['scenarios']) >= 24; print('OK', len(d['scenarios']))"`
- [ ] Confirm every scenario id is unique:
      `.venv/bin/python -c "import json; ids = [s['id'] for s in json.load(open('evals/datasets/architecture_intent_nl_golden.json'))['scenarios']]; assert len(ids) == len(set(ids)); print('OK, unique')"`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(evals): add provider-neutral Layer 2 natural-language golden dataset
      ```

---

## Task 8 — Layer 2 evaluator + runner

**Files**
- Create: `evals/evaluators/architecture_intent_nl.py`
- Create: `evals/scenarios/architecture_intent_nl_loader.py`
- Create: `evals/scenarios/architecture_intent_nl_runner.py`
- Create: `tests/unit/evals/test_architecture_intent_nl_evaluators.py`

**Interfaces**
- Loader: mirrors `architecture_intent_resolver_loader.py`'s exact
  shape — `Scenario`/`ExpectedOutcome` dataclasses,
  `load_architecture_intent_nl_golden_dataset(path) -> tuple[Scenario, ...]`,
  fail-closed structural validation (`DatasetError` on malformed
  entries, duplicate-id detection).
- Evaluators: `evaluate_schema_validity(scenario, intent: ArchitectureIntent | Exception) -> EvalResult`
  (handles both a successfully parsed intent and a raised
  `IntentInterpreterError`, since a Layer 2 call can legitimately fail
  at the provider/parsing level for some scenarios — the evaluator must
  classify that outcome, not crash on it);
  `evaluate_semantic_fields(scenario, intent: ArchitectureIntent) -> EvalResult`
  (exact `workload_type`/`interaction_pattern`/`capabilities` match,
  `user_provided_hints` where the scenario specifies it,
  `unresolved_questions_expected` boolean check);
  `evaluate_forbidden_authority_absence(scenario, raw_payload: dict) -> EvalResult`
  (asserts no extraneous top-level key beyond `ArchitectureIntent`'s own
  field set — the "forbidden authority leakage" check, run against the
  *raw* payload before Pydantic validation, so it also catches a
  payload that would otherwise be silently accepted by
  `model_validate`'s default "ignore extra fields" behavior — **verify
  at implementation time whether `ArchitectureIntent`'s `model_config`
  needs `extra="forbid"` added for this check to be meaningful; if it
  currently allows extra fields silently, this is a genuine gap
  discovered during Batch 23 implementation, not something to
  silently work around — STOP and report if so, per Global Constraint 2
  forbidding a change to `ArchitectureIntent` without going back to
  design**); `evaluate_resolver_compatibility(scenario, intent) -> EvalResult`
  (only for scenarios where `expected.workload_type` is set — reuses
  the *existing* `ArchitectureResolver` directly, no duplicated logic,
  confirming the produced intent actually resolves the way Layer 1
  already proved that combination should).
- Runner: `run_architecture_intent_nl_evals(*, interpreter: IntentInterpreterPort, dataset_path=DEFAULT, max_attempts: int = 2) -> EvalSuiteResult`.
  **The runner never constructs an OpenAI (or any provider) object
  itself** — `interpreter` is injected. The runner enforces the hard
  call ceiling from Global Constraint/design §14:
  `len(dataset) * max_attempts` total interpreter calls, raising a
  plain `RuntimeError` if the underlying interpreter is somehow invoked
  more than that (a static, pre-computed ceiling, not a soft/approximate
  one).

**Steps**

- [ ] Write `tests/unit/evals/test_architecture_intent_nl_evaluators.py`
      using a locally defined `FakeIntentInterpreter` (per the existing
      fakes-in-tests convention) configured to return canned intents or
      raise canned errors, with:
  1. `test_evaluate_schema_validity_pass_for_valid_intent`
  2. `test_evaluate_schema_validity_fail_for_unexpected_interpreter_error`
  3. `test_evaluate_semantic_fields_pass_for_exact_match`
  4. `test_evaluate_semantic_fields_fail_for_wrong_workload_type`
  5. `test_evaluate_semantic_fields_fail_for_wrong_capability_set`
  6. `test_evaluate_semantic_fields_checks_user_provided_hints_when_specified`
  7. `test_evaluate_forbidden_authority_absence_pass_for_clean_payload`
  8. `test_evaluate_forbidden_authority_absence_fail_for_extraneous_key`
  9. `test_evaluate_resolver_compatibility_reuses_existing_resolver`
     (assert it calls the real `ArchitectureResolver`, not a
     reimplementation — e.g. by asserting the resolved `matched_pattern`
     matches what `ArchitectureResolver` alone would produce for the
     same intent)
  10. `test_confidence_field_never_referenced_by_any_nl_evaluator`
      (mechanical source-text check, mirroring
      `test_resolver_source_contains_no_confidence_attribute_reference`)
  11. `test_runner_never_constructs_a_provider_object_itself` (mechanical
      AST check over `architecture_intent_nl_runner.py`'s source: no
      `openai`/`IntentInterpreterProvider`/`create_intent_interpreter`
      reference anywhere in the file)
  12. `test_runner_enforces_hard_call_ceiling` (fake interpreter that
      counts its own calls unboundedly; runner configured with a tiny
      `max_attempts`/dataset size; assert `RuntimeError` once the
      ceiling is exceeded, and that the ceiling is exactly
      `len(dataset) * max_attempts`)
- [ ] Run: `.venv/bin/python -m pytest tests/unit/evals/test_architecture_intent_nl_evaluators.py -v`
      Expected failure: `ModuleNotFoundError`.
- [ ] Implement the loader, evaluators, and runner.
- [ ] Run the same command again. Expected: `12 passed`.
- [ ] Run: `.venv/bin/python -m pytest tests/unit/ -q`
- [ ] Run: `.venv/bin/ruff check evals/evaluators/architecture_intent_nl.py evals/scenarios/architecture_intent_nl_loader.py evals/scenarios/architecture_intent_nl_runner.py tests/unit/evals/test_architecture_intent_nl_evaluators.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(evals): add provider-neutral Layer 2 evaluators and runner
      ```

---

## Task 9 — Activate the `real_llm` integration skeleton

**Files**
- Modify: `tests/integration/test_architecture_intent_nl_real_model_eval.py`

**Interfaces**
- Replaces the inert placeholder body with:
  ```python
  @pytest.mark.skipif(
      os.environ.get("IAC_AGENT_LLM_PROVIDER") is None,
      reason="no real LLM provider configured (IAC_AGENT_LLM_PROVIDER unset)",
  )
  def test_natural_language_to_intent_real_model_eval():
      config = load_intent_interpreter_config_from_env()
      api_key = load_openai_api_key_from_env()  # exact loader depends on config.provider — see note below
      interpreter = create_intent_interpreter(config, api_key=api_key)
      suite = run_architecture_intent_nl_evals(interpreter=interpreter)
      print("\n" + format_summary(suite, title="Architecture Intent NL Golden Evals (Layer 2)"))
      assert suite.failed == 0
      assert suite.errored == 0
  ```
  This is the **only** file in the whole plan that is allowed to call
  `create_intent_interpreter` with a real `api_key` and no injected
  fake `client` — and it is still fully gated behind `real_llm` +
  the unconditional `skipif`. Note: since credential loading is
  provider-specific (Global Constraint from the design), this test's
  credential-loading line is itself a small `match config.provider`
  (a **second**, test-only, non-`src/` occurrence — acceptable since
  Task 6's isolation test only counts occurrences under `src/`) or,
  more simply for a single-provider batch, calls
  `load_openai_api_key_from_env()` directly since `OPENAI` is the only
  configured provider this batch supports — implementer's choice,
  documented in the commit.
- The `pytest.mark.real_llm` line, the module docstring's honesty about
  "makes a real network call once activated," and the unconditional
  `pytest.skip()` fallback from Batch 21 are all **removed** as part of
  this activation (the whole point of this task) — replaced by the
  real assertion above, still behind the same two-layer gate
  (`real_llm` marker + `IAC_AGENT_LLM_PROVIDER` env check).

**Steps**

- [ ] Run: `.venv/bin/python -m pytest -m real_llm -v` **before** editing
      — expected: `1 skipped` (confirms the current inert baseline one
      more time before changing this file).
- [ ] Edit the file exactly as specified above.
- [ ] Run: `.venv/bin/python -m pytest -m real_llm -v` again **without**
      `IAC_AGENT_LLM_PROVIDER` set — expected: `1 skipped` (the
      skip-gate still works after activation; **zero** network call
      happens even now, since the test body is never entered).
- [ ] Run: `.venv/bin/python -m pytest --collect-only -q 2>&1 | tail -5`
      — expected: clean collection, no marker warnings, no import
      errors (confirms the file still imports cleanly even for
      contributors without `openai` installed — the new imports this
      file needs, e.g. `create_intent_interpreter`, must not force an
      eager `openai` import either; this is the same lazy-import
      discipline from Task 6, now proven at the integration-test level
      too).
- [ ] Run: `.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q`
      — expected: no regressions, same baseline behavior as before this
      task (this file was already excluded from that command by its
      own marker; this run just re-confirms the exclusion still holds
      after the edit).
- [ ] Run: `.venv/bin/ruff check tests/integration/test_architecture_intent_nl_real_model_eval.py`
- [ ] Run: `git diff --check`
- [ ] Commit:
      ```
      feat(evals): activate the real_llm OpenAI Layer 2 integration test
      ```

---

## Task 10 — Documentation, final deterministic validation, and the human checkpoint

**Files**
- Create: `docs/real-llm-intent-interpreter.md`
- Modify: `README.md` (one sentence added to the existing doc-reference
  list, mirroring the exact pattern used for `docs/ci.md` in Batch 22 —
  no rewrite)

**Documentation content (minimal, per the approved design's own
non-goal against turning this into a documentation rewrite):**
- How to select a provider/model (`IAC_AGENT_LLM_PROVIDER`,
  `IAC_AGENT_LLM_MODEL`), with `openai`/`gpt-5-nano` as the documented
  starting example — not a hardcoded requirement.
- How to install the optional dependency (`pip install -e ".[openai]"`).
- `OPENAI_API_KEY` — required only when actually invoking the real
  adapter, never for ordinary development or CI.
- How to run `pytest -m real_llm` and what it costs (real network call,
  real token spend, ~24 calls expected / ≤48 worst case).
- The privacy boundary: raw prompts and raw responses are never
  persisted or logged by this project, by default, ever.
- How a future provider (Anthropic/Bedrock) would be added — one new
  adapter file, one new `match` arm, one new extras group — explicitly
  *not* implemented in this batch.

**Steps**

- [ ] Write `docs/real-llm-intent-interpreter.md` covering exactly the
      six points above.
- [ ] Add one sentence to `README.md`'s existing doc-reference
      paragraph, exactly mirroring how `docs/ci.md` was added in Batch
      22.
- [ ] Run the **complete deterministic validation suite** (this is the
      full local proof this entire plan produces zero behavior change
      to anything except what it explicitly adds):
      1. `.venv/bin/ruff check .` — expected: `All checks passed!`
      2. `.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q`
         — expected: previous baseline count plus every new test from
         Tasks 1–9, all passed, 0 failed. Report the actual number —
         do not assert a specific pre-computed total in this plan.
      3. `.venv/bin/python -m pytest -m real_tool -q` — expected:
         unchanged from the pre-Batch-23 baseline (no task in this plan
         adds a `real_tool`-marked test).
      4. `.venv/bin/python -m pytest -m real_llm -v` (still with
         `IAC_AGENT_LLM_PROVIDER` unset) — expected: `1 skipped`, 0
         network calls.
      5. `git diff --check` — expected: clean.
      6. Clean-room grep over every file this plan touched:
         `grep -rniE "gitlab|atlantis|clubhub|royalbeyond|pablo|galeana" src/iac_agent/intent/adapters/ src/iac_agent/app/config.py src/iac_agent/app/composition.py evals/datasets/architecture_intent_nl_golden.json evals/evaluators/architecture_intent_nl.py evals/scenarios/architecture_intent_nl_*.py docs/real-llm-intent-interpreter.md`
         — expected: no output.
      7. Confirm `.github/workflows/ci.yml` has zero diff against the
         Batch 22 merged version: `git diff origin/main -- .github/workflows/ci.yml`
         — expected: empty (no task in this plan touches CI).
      8. Confirm no `AWS_*`/AWS-OIDC/`terraform apply`/`terraform destroy`
         string was introduced anywhere in the new files:
         `grep -rniE "AWS_ACCESS_KEY|AWS_SECRET|id-token|terraform apply|terraform destroy" src/iac_agent/intent/adapters/ src/iac_agent/app/composition.py src/iac_agent/app/config.py`
         — expected: no output.
- [ ] **STOP HERE. Do not proceed to Task 11 without separate, explicit
      human authorization.** Report at this checkpoint:
      - Deterministic test status (exact numbers from step 2 above).
      - Configured model for the intended first real run (proposed:
        `gpt-5-nano`, confirmed still available and Structured-Outputs-
        capable at implementation time — re-verify, do not assume the
        design doc's research is still current by the time this task
        actually runs).
      - Number of Layer 2 scenarios (from Task 7, expected 24).
      - Expected provider calls (24) and maximum (`≤48`).
      - Confirmation `OPENAI_API_KEY` is required and not yet provided.
      - An approximate expected cost, computed from the configured
        model's current published per-token pricing and a rough
        per-scenario token estimate (state the estimate and the pricing
        source explicitly — this is a small enough number that even a
        rough estimate is meaningful for the human's go/no-go decision).
- [ ] Commit (documentation only — the validation run itself produces no
      file changes to commit):
      ```
      docs(intent): document real LLM provider selection, cost, and privacy boundary
      ```

---

## Task 11 *(gated — requires separate human authorization, not part of this plan's automatic sequence)*

Only after the human explicitly authorizes it following Task 10's
checkpoint report:

- [ ] Set `IAC_AGENT_LLM_PROVIDER=openai`, `IAC_AGENT_LLM_MODEL=gpt-5-nano`
      (or whatever was confirmed at the checkpoint), and `OPENAI_API_KEY`
      in the local shell environment only — never committed, never
      logged.
- [ ] Run: `IAC_AGENT_LLM_PROVIDER=openai IAC_AGENT_LLM_MODEL=<model> pytest -m real_llm -v`
- [ ] Record the actual result per scenario.
- [ ] For every failure, apply the approved triage (design §13) **before
      concluding anything about the model**:
      - **A — invalid/ambiguous golden scenario:** fix the scenario in
        Task 7's dataset, re-run.
      - **B — prompt-contract defect:** fix the prompt in Task 3's
        adapter, bump `_PROMPT_VERSION`, re-run.
      - **C — adapter/schema defect:** fix the adapter, re-run.
      - **D — genuine model limitation:** the *only* category that
        justifies evaluating a different, currently-suitable
        Structured-Outputs-capable OpenAI model — verified at this
        time, not assumed from the design document's earlier research.
- [ ] The five boundary/safety scenarios
      (`case10`–`case14`) are hard requirements — a failure on any of
      them is never accepted regardless of the overall pass rate, and
      is triaged with extra scrutiny (a genuine model safety/reliability
      gap here is a stronger signal than a semantic-field mismatch
      elsewhere).
- [ ] Report the final real-model result, the tested model ID, and any
      triage actions taken, to the human. **Do not merge, push, or
      proceed to any further batch without a separate review of this
      result.**

---

## Coverage cross-reference (design requirement → task)

| Design/task requirement | Task |
|---|---|
| Provider-neutral config, fail-closed unknown provider | 1 |
| Optional OpenAI dependency, bare install unaffected | 2 |
| Structured-output boundary, adapter-injected `schema_version`, nullable handling | 3 |
| Error normalization (existing 5-type hierarchy only), bounded retry/timeout | 4 |
| Privacy-safe telemetry, no raw content logged | 5 |
| Composition-boundary dispatch (exactly one), lazy `openai` import, multi-provider isolation proofs | 6 |
| Shared provider-neutral Layer 2 dataset, ~24 scenarios, EN/ES + adversarial + paraphrase + mixed + noisy | 7 |
| Deterministic evaluators, resolver-compatibility reuse, no LLM-as-judge, `confidence` excluded from PASS/FAIL | 8 |
| `real_llm` activation, still double-gated, zero calls until explicitly run | 9 |
| Documentation, full deterministic validation, human checkpoint before any real call | 10 |
| Failure triage (A–D), hard boundary-scenario requirement, evidence-driven escalation | 11 (gated) |

## Self-review checklist

- [x] No task calls OpenAI for real, requires `OPENAI_API_KEY`, or
      installs anything beyond `pip install -e ".[openai]"` (a local,
      optional, implementer-only step in Task 3) before Task 10's
      checkpoint.
- [x] Bare `pip install -e .` never installs `openai` — proven by an
      explicit end-to-end check in Task 6, not just a `pyproject.toml`
      declaration.
- [x] Raw prompts and raw provider responses are never logged or
      persisted — proven by dedicated tests in Task 5.
- [x] No credential ever reaches `ArchitectureIntent`, `IntentInterpreterConfig`,
      `WorkflowState`, a SQLite checkpoint, an eval dataset, a log line,
      or git — proven by Task 1's `SecretStr`-repr test and Task 5's
      telemetry tests.
- [x] Every raw payload passes through `parse_intent_payload` before
      becoming an `ArchitectureIntent` — no code path in Task 3
      bypasses it.
- [x] No architecture decision moves into the model — the resolver
      allowlist is never disclosed (Task 3's prompt contract), and
      `ArchitectureResolver`/`SecurityGate`/HITL/Terraform execution
      policy are never touched by any task.
- [x] `Tool Validation` is never made a required check — no task
      touches `.github/workflows/ci.yml` at all (verified explicitly in
      Task 10).
- [x] No Anthropic/Bedrock implementation, no provider fallback —
      verified structurally by Task 6's isolation tests and Task 4's
      no-fallback test.
- [x] Every command in every task was derived from, and is consistent
      with, the existing repository conventions verified in the
      "Repository verification snapshot" — none invented.
- [x] No placeholder/TODO/"similar to Task N" language — every task
      names its exact files, exact test functions, exact commands, and
      exact expected results.

# Design Spec: Real LLM Intent Interpreter + Layer 2 Evals (Batch 23, design-only)

Status: **DRAFT — awaiting human review**
Scope: **design only** — no production code, no tests, no dependency
changes, no SDK installation, no real model call accompanies this
document.

## 0. Purpose and scope

Batch 21 built the platform's first probabilistic boundary
(`IntentInterpreterPort → ArchitectureIntent → ArchitectureResolver →
IacRequestSpec`) and its offline Layer 1 eval suite, but shipped no
concrete interpreter — every test uses a `FakeIntentInterpreter`. Batch
22 added CI quality gates and a protected `main`. This batch designs
the first **real** adapter and the Layer 2 (real-model) eval layer the
Batch 21 design's own §22.1 explicitly deferred. It does not redesign
anything Batch 21 already locked in.

**Golden rule, unchanged and load-bearing for every decision below: the
LLM interprets, deterministic code decides.**

## 1. Read-only discovery: current architecture (re-verified at `main` `8581cc7`)

- `IntentInterpreterPort.interpret(self, *, natural_language_request: str, request_id: str) -> ArchitectureIntent`
  — one method, `Protocol`, mirrors `SourceControlPort` exactly. Success
  returns the value; failure raises an `IntentInterpreterError` subtype.
- `ArchitectureIntent` (frozen Pydantic model): `schema_version: Literal["1"]="1"`,
  `workload_type: WorkloadType` (`API|WORKER|STORAGE|UNSPECIFIED`),
  `interaction_pattern: InteractionPattern` (`SYNCHRONOUS|ASYNCHRONOUS|UNSPECIFIED`),
  `capabilities: frozenset[Capability]` (`HTTP_ENDPOINT|QUEUE_PROCESSING|PERSISTENCE|OBJECT_STORAGE`,
  exactly four, closed), `logical_name_hint: str|None` (≤128),
  `user_provided_hints: tuple[AwsServiceHint,...]` (≤8, `SQS|S3|DYNAMODB|LAMBDA|API_GATEWAY`,
  non-authoritative), `assumptions`/`unresolved_questions: tuple[str,...]`
  (≤8 each, non-authoritative), `confidence: float|None` (0.0–1.0,
  non-authoritative — mechanically proven: `resolver.py`'s own source
  text contains no `.confidence` reference).
- `parse_intent_payload(raw_payload) -> ArchitectureIntent` (`port.py`):
  schema-version gate first (`IntentSchemaVersionUnsupportedError`),
  then `ArchitectureIntent.model_validate` (`IntentValidationError` on
  any Pydantic failure) — the one authoritative local validation
  boundary every adapter's output must pass through.
- `IntentInterpreterError` hierarchy: base + `IntentSchemaVersionUnsupportedError`,
  `IntentValidationError`, `IntentProviderUnavailableError`,
  `IntentProviderTimeoutError`, `IntentProviderRefusalError` — five
  members, unchanged, sufficient for every mapping this design needs
  (§7 — no new domain error is introduced).
- `ArchitectureResolver.resolve(*, intent, request_id) -> ResolutionResult`
  — pure, closed three-row allowlist (`API+SYNCHRONOUS+{HTTP_ENDPOINT}`,
  `WORKER+ASYNCHRONOUS+{QUEUE_PROCESSING,PERSISTENCE}`,
  `STORAGE+{OBJECT_STORAGE}`), fail-closed default. Untouched by this
  batch.
- `IntentResolutionService.submit(*, request_id, natural_language_request) -> IntentSubmissionResult`
  — `interpret → resolve → (only if resolved) IacApplication.submit()`.
  `natural_language_request` is a parameter only, never assigned to any
  field, never persisted — verified directly in `service.py`.
- `real_llm` marker (registered in `pyproject.toml`) + one test file,
  `tests/integration/test_architecture_intent_nl_real_model_eval.py` —
  double-guarded (`skipif(IAC_AGENT_LLM_PROVIDER is None)` **and** an
  unconditional `pytest.skip()` in the body), zero real calls today.
  Batch 22 CI confirmed this stays outside `Quality`/`Tests`/`Tool
  Validation`.
- Dependencies (`pyproject.toml`): `pydantic`, `langgraph`,
  `langgraph-checkpoint-sqlite` — no LLM SDK, no `boto3`, one extras
  group (`dev`) today.
- Composition-root precedent (`iac_agent.app.config`/`iac_agent.app.composition`):
  `ApplicationConfig` (non-secret, dataclass) + `load_application_config_from_env`
  (env-reading, `MissingConfigurationError` on missing required value) +
  `load_github_token_from_env` (`SecretStr`, loaded separately from
  config) + `open_application` (the one composition root that
  constructs real adapters; "No domain module or LangGraph node reads
  `os.environ` — this is the only place in the entire codebase that
  does"). This is the exact pattern this design extends for the LLM
  side, not a new invented one.
- Port/adapter co-location precedent (`iac_agent.git.port`/`iac_agent.git.github`):
  a narrow `Protocol`, typed exceptions, and the concrete adapter
  co-located in the *same* package — never a generic top-level
  `adapters/` tree. Batch 21's own design already applied this to
  `iac_agent.intent/` and explicitly rejected a generic
  `src/iac_agent/adapters/intent/` layout on the same grounds.

## 2. Provider decision

Three candidates were compared against this repository's actual
constraints (structured-output fit, dependency footprint, credential
surface, portfolio consistency with "no AWS account required") — full
comparison in the brainstorming record; summarized here as the decision
of record:

| # | Provider | Verdict |
|---|---|---|
| A | OpenAI | **Selected — first reference adapter.** Narrowest new dependency (one thin SDK), one API key, native Structured Outputs (`response_format: json_schema, strict`), zero AWS coupling. |
| B | Anthropic | Deferred, not rejected. Comparable fit (forced tool-use `input_schema` has slightly cleaner native-optional-field support than OpenAI's all-required strict mode) — a fully viable *future* second adapter, not chosen first only because one reference implementation was the approved Batch 23 scope. |
| C | AWS Bedrock | Deferred. Would require adding `boto3` (broad, general-purpose SDK vs. either provider's narrow client) **and** a net-new AWS IAM credential relationship this repository has never needed for anything — undermining the project's own "no AWS account required" story for no repository-specific benefit, since there is no existing AWS infrastructure here to piggyback on. |

**Human-approved direction (supersedes a single-provider choice):** the
architecture is **multi-provider by design** — `IntentInterpreterPort`
is the only contract any adapter implements, and the domain never knows
which provider produced a given `ArchitectureIntent`. Batch 23
*implements* OpenAI only; Anthropic and Bedrock remain designed-for,
not built (§13, §14).

## 3. Multi-provider composition boundary

Two small additions, no new package tree, mirroring §1's own
`ApplicationConfig`/`open_application` precedent exactly:

```python
# iac_agent/app/config.py (extended)

class IntentInterpreterProvider(StrEnum):
    OPENAI = "openai"
    # ANTHROPIC = "anthropic"  # future — not a member yet
    # BEDROCK = "bedrock"      # future

@dataclass(frozen=True)
class IntentInterpreterConfig:
    provider: IntentInterpreterProvider
    model: str

def load_intent_interpreter_config_from_env(env: Mapping[str, str] | None = None) -> IntentInterpreterConfig:
    """Reads IAC_AGENT_LLM_PROVIDER and IAC_AGENT_LLM_MODEL. An
    unrecognized provider string fails at IntentInterpreterProvider
    construction — StrEnum's own closed-membership behavior, the same
    fail-closed mechanism WorkloadType/Capability already rely on —
    re-raised as MissingConfigurationError, mirroring every other
    required-value failure in this module. No silent fallback is
    possible by construction."""
```

```python
# iac_agent/app/composition.py (extended)

def create_intent_interpreter(
    config: IntentInterpreterConfig, *, api_key: SecretStr
) -> IntentInterpreterPort:
    match config.provider:
        case IntentInterpreterProvider.OPENAI:
            return OpenAIIntentInterpreter(model=config.model, api_key=api_key)
```

This `match` is the **only** place in the entire codebase that ever
branches on provider identity — one arm today, one new arm per future
provider, never an `if provider == "openai"` scattered elsewhere.
`IntentResolutionService`, `ArchitectureResolver`, and every domain type
remain exactly as provider-blind as `Application`/`build_iac_workflow`
already are about which concrete `SourceControlPort` they were handed.

**Configuration, provider-neutral:** `IAC_AGENT_LLM_PROVIDER`,
`IAC_AGENT_LLM_MODEL` — both required, no default (matches the existing
`GITHUB_OWNER`-style "no safe default" convention exactly), matching
the `IAC_AGENT_`-prefix already used for `IAC_AGENT_WORKSPACE_ROOT`/
`IAC_AGENT_STATE_DB`.

**Credentials, provider-specific, never in config:** `OPENAI_API_KEY`
(OpenAI's own SDK-recognized name, mirroring the `GITHUB_TOKEN`
precedent of reusing a third party's own conventional name), loaded by
a small `load_openai_api_key_from_env() -> SecretStr`, passed into
`create_intent_interpreter` only at construction — never stored on
`IntentInterpreterConfig`, never logged, never reaches
`ArchitectureIntent` or `WorkflowState`. A future Bedrock adapter's
credential is `boto3`'s own credential-chain resolution — structurally
different from a bearer key, which is exactly why credential loading
stays adapter-specific rather than one artificial
`load_credentials(provider)` abstraction.

## 4. Proposed package layout

```
src/iac_agent/intent/
    ... (unchanged: __init__.py, models.py, resolver.py, naming.py, port.py, service.py)
    adapters/
        __init__.py
        openai.py          # OpenAIIntentInterpreter — this batch's only new adapter file
        # anthropic.py     # future, not created this batch
        # bedrock.py       # future, not created this batch
```

A new `adapters/` **sub**-package *inside* `iac_agent.intent` — not a
generic top-level `iac_agent/adapters/` tree, which Batch 21's own
design already rejected as inconsistent with this repository's
co-location convention. The subpackage exists only to keep the flat
`models.py`/`resolver.py`/`naming.py`/`port.py`/`service.py` layout
uncluttered as sibling provider files accumulate.

`iac_agent/app/config.py` and `iac_agent/app/composition.py` are
extended in place (§3) — no new files at the application layer.

## 5. OpenAI reference adapter: structured-output boundary

```
untrusted bytes/object
        ↓
OpenAIIntentInterpreter.interpret()   [this adapter]
        ↓
parse_intent_payload()                [existing, unchanged, authoritative]
        ↓
ArchitectureIntent
        ↓
ArchitectureResolver                  [existing, unchanged, deterministic]
```

Uses OpenAI's Structured Outputs (`response_format={"type": "json_schema", "strict": true}`),
which requires every schema property to be listed as `required` (no
true optionality in strict mode). Two adapter-owned normalization
decisions, both resolvable without any domain change:

- **The adapter sets `schema_version` itself — the model never sees or
  produces that field.** Removes an entire class of malformed/
  adversarial output at zero cost: the model cannot get a field wrong,
  or be prompted to change it, if it is never asked to produce it.
- Genuinely-optional fields (`logical_name_hint`, `confidence`) are
  declared nullable in the request-time schema; a returned `null`
  passes straight through to `parse_intent_payload` unchanged (Pydantic
  treats an explicit `None` identically to the field's own default).
  The three bounded-tuple fields (`user_provided_hints`, `assumptions`,
  `unresolved_questions`) are declared as plain (non-nullable) arrays,
  empty array being the natural "nothing here" value.

**OpenAI's own schema enforcement is adapter-level validation only,
never a substitute for local validation.** `parse_intent_payload`
remains the sole authoritative boundary regardless of provider — this
is true today for a hypothetical adapter and stays true for every
future one.

**Non-determinism configuration (provider-neutral rule, adapter-specific
value):** the architecture requires only "use the lowest-variance
deterministic configuration supported and recommended by the selected
provider/model for structured semantic extraction." The OpenAI adapter
picks its own concrete setting (e.g. a temperature/sampling parameter
appropriate to the configured model family); **no temperature,
reasoning-effort, or other sampling parameter ever appears in
`ArchitectureIntent`, `IntentInterpreterPort`, or the Layer 2 golden
dataset** — this stays entirely inside the adapter, exactly like model
identity does.

## 6. Error normalization

Mapped using **only** the five existing `IntentInterpreterError`
subtypes — no new domain error is introduced, so no widening of the
domain occurs:

| OpenAI SDK condition | Mapped to | Retryable? |
|---|---|---|
| Connection-level failure | `IntentProviderUnavailableError` | Yes |
| Rate limit | `IntentProviderUnavailableError` | Yes |
| Timeout | `IntentProviderTimeoutError` | Yes |
| Response's own `refusal` field set (Structured Outputs' explicit safety-refusal signal) | `IntentProviderRefusalError` | No |
| Any other malformed/unparseable payload | → `parse_intent_payload` → `IntentValidationError` | No |
| Missing `OPENAI_API_KEY` | `MissingConfigurationError`, at **composition time** — fails before any `interpret()` call, exactly like a missing `GITHUB_TOKEN` today | N/A |
| Bad/revoked key rejected at request time | `IntentProviderUnavailableError` | No — a per-process retry cannot fix a bad key |

Rate limits and connection failures are grouped with
`IntentProviderUnavailableError` rather than `IntentProviderRefusalError`
deliberately: a refusal is a content-level decision where retrying the
identical prompt cannot help; a rate limit or dropped connection is an
operational condition where a short retry might.

**Retries:** max **2 attempts total** (1 retry) for the three
retryable categories only, one short fixed backoff between attempts,
one overall per-call timeout (adapter-configured, documented default —
proposed 30s, never a silently-inherited SDK default). `IntentProviderRefusalError`
and any `parse_intent_payload` failure are **never** retried — retrying
an identical prompt against a deterministic refusal or schema mismatch
cannot produce a different result, and would be exactly the
uncontrolled prompt-repair loop this batch must not build.

## 7. Versioned prompt contract

A module-level, versioned instruction text co-located with the adapter
(`_PROMPT_VERSION = "1"` in `adapters/openai.py`, bumped whenever the
wording changes materially, recorded in telemetry §9). Its entire
responsibility: extract `workload_type`/`interaction_pattern`/
`capabilities`/`logical_name_hint`/`user_provided_hints`/`assumptions`/
`unresolved_questions`/`confidence` from the request — nothing else. It
explicitly states what it must never do: write Terraform, choose IAM,
judge security, call tools, execute commands, browse, touch GitHub, or
choose from the resolver's allowlist. **The allowlist rows are never
disclosed to the model** — revealing "only these three combinations
resolve" would tempt it to bend an honest-but-unsupported request into
a resolvable shape, which is the resolver's fail-closed job, never the
interpreter's.

**AWS service words:** if the user explicitly writes a term like SQS,
Lambda, DynamoDB, S3, or API Gateway, the contract permits recording it
*only* via `user_provided_hints` (the existing closed `AwsServiceHint`
vocabulary) — never as an authoritative architecture choice. Unchanged
from Batch 21: the resolver never reads this field (§4.3 of the Batch
21 design, re-verified: `resolver.py` matches only on
`workload_type`/`interaction_pattern`/`capabilities`).

## 8. Prompt-injection containment

Structural containment is unchanged and remains the actual guarantee:
closed enums, bounded strings, a schema-only output channel, and a
resolver that never reads `assumptions`/`unresolved_questions`/hints.
This batch adds one prompt-level, defense-in-depth instruction on top:
the contract tells the model the request text is *data to interpret*,
never *instructions to follow*, and that any embedded attempt to
redirect its behavior should be reflected honestly as an
`assumptions`/`unresolved_questions` entry rather than obeyed. **Prompt
wording can never be proven correct by inspection alone — only the
Layer 2 adversarial cases (§10, categories 10–14) are the actual proof**,
exactly why they are evals and not merely a design assertion.

## 9. Privacy and telemetry

**Never persisted or logged by default:** the raw natural-language
request, the raw provider response body. Unchanged from Batch 21 and
re-verified directly against `service.py`: `natural_language_request`
is a parameter only, never assigned to any field. The adapter upholds
the identical rule for its own logging.

**Safe telemetry (adapter-level metadata only):** `request_id`,
`provider`, `model`, `prompt_version`, `latency_ms`, `attempt_count`,
`outcome_category` (schema-valid / validation-error / timeout /
unavailable / refusal), and token counts if the SDK exposes them
(counts only, never content).

## 10. Layer 2 eval architecture

One shared, provider-neutral dataset — `evals/datasets/architecture_intent_nl_golden.json`
— each entry `{id, description, natural_language_request, expected}`,
never a provider-specific expected value. The **same** scenarios must
eventually run against OpenAI, Anthropic, or Bedrock without dataset or
evaluator changes — only the injected `IntentInterpreterPort`
implementation differs.

**~24 scenarios:**
- Paired English/Spanish (2 each) for 9 core semantic categories:
  `case1_sync_api_{en,es}`, `case2_async_worker_{en,es}`,
  `case3_persistence_worker_{en,es}`, `case4_object_storage_{en,es}`,
  `case5_explicit_hints_{en,es}`, `case6_ambiguous_architecture_{en,es}`,
  `case7_missing_interaction_pattern_{en,es}`,
  `case8_unsupported_request_{en,es}`, `case9_irrelevant_non_iac_{en,es}`
  — 18 scenarios.
- One representative English case each for 5 adversarial/boundary
  categories: `case10_prompt_injection_ignore_instructions`,
  `case11_request_terraform_generation`,
  `case12_request_iam_admin_permissions`,
  `case13_request_bypass_security`, `case14_request_terraform_apply`.
- `case15_paraphrase_of_case1` (robustness to wording, not keywords).
- `case16_mixed_es_en` (mixed-language request).
- `case17_harmless_noise` (clear intent wrapped in irrelevant prose).

**Deterministic assertions per scenario:** `schema_valid: bool`; when
true — exact `workload_type`, exact `interaction_pattern`, exact
`capabilities` set; `user_provided_hints` asserted (exact-set) only for
the case-5 pair; a boolean `unresolved_questions_expected` where
ambiguity should honestly be flagged (never exact text); and
`forbidden_top_level_keys_absent: true` on every scenario — a
structural, defensive re-check that the parsed payload never carries an
extraneous key like `terraform`/`iam_policy`/`security_status`.

**Runner:** `run_architecture_intent_nl_evals(*, interpreter: IntentInterpreterPort, dataset_path=DEFAULT)`
— the interpreter is **injected**, the runner has zero provider
knowledge. `tests/integration/test_architecture_intent_nl_real_model_eval.py`
becomes the one place that calls
`create_intent_interpreter(load_intent_interpreter_config_from_env(), ...)`
and hands the result to this runner, still gated behind the unchanged
`real_llm` marker. Where useful, the evaluator re-runs the *existing*
`ArchitectureResolver` on the produced intent and reuses Layer 1's own
resolution-outcome comparison rather than duplicating logic — proving
end-to-end viability without re-implementing Terraform/security/
workflow evals.

## 11. PASS/FAIL policy

Binary, reusing Layer 1's own `EvalStatus`/`EvalResult` convention
exactly: PASS only if every assertion for a scenario matches; otherwise
FAIL. `ERROR` is reserved for the evaluator itself malfunctioning (an
unexpected exception type), never for "the model got a field wrong" —
that is always FAIL. Every assertion is a plain equality/membership/
absence check against the already-parsed `ArchitectureIntent` — **no
LLM ever grades another LLM's output**. `confidence` is recorded for
diagnostic reporting only; it never participates in the PASS/FAIL
decision.

## 12. Non-determinism strategy

Explicitly acknowledged, not hidden: single-run per scenario per
invocation by default — no repeated-sampling/majority-vote (that is the
"ensemble inference" the non-goals forbid, and would multiply cost for
marginal gain). Assertions are chosen because they are genuinely
deterministic classification decisions a correctly-behaving model
should get consistently right for a clearly-written scenario; nothing
fuzzy (exact wording, exact assumption text) is ever asserted. A
scenario that fails intermittently is real signal — triaged per §13,
never resolved by weakening the assertion.

## 13. Model acceptance and escalation policy

**Initial candidate:** `gpt-5-nano` — verified (not assumed) as OpenAI's
current cheapest Structured-Outputs-capable model, and per current
vendor guidance specifically suited to JSON-only classification/
extraction tasks (its documented weakness is degradation on *non-JSON*
grammars, irrelevant here since only JSON is ever requested).

**Acceptance target:** **all** required golden scenarios must PASS —
no percentage threshold is set in advance of real execution. The five
boundary/safety scenarios (`case10`–`case14`: prompt injection,
Terraform-generation request, IAM/admin request, security-bypass
request, `terraform apply` request) are **hard requirements** — a
failure on any of these is never accepted regardless of overall
pass-rate.

**Failure triage (required before any model-escalation decision):**

| Category | Meaning | Action |
|---|---|---|
| A | Invalid/ambiguous golden scenario | Fix or remove the scenario |
| B | Prompt-contract defect | Fix the prompt, bump `_PROMPT_VERSION` |
| C | Adapter/schema defect | Fix the adapter's request/response handling |
| D | Genuine provider/model capability/reliability limitation | **Only this category is evidence for model escalation** |

```
gpt-5-nano
    ↓
Layer 2
    ↓
failure?
    ├─ scenario defect (A) → fix scenario
    ├─ prompt defect (B)   → fix prompt, bump version
    ├─ adapter defect (C)  → fix adapter
    └─ model limitation (D)
            ↓
    verify the current suitable Structured-Outputs-capable
    OpenAI model at implementation/evaluation time,
    record the tested model ID
```

**No escalation target is hardcoded now.** `gpt-5-mini` is documented
here only as today's known stronger option per current research, not as
an eternal fixed successor — the OpenAI model catalog will keep
changing, and the *process* (verify, don't assume) is what this design
locks in, not a specific future model name. A failure is never resolved
by weakening a valid assertion merely to preserve the cheaper model.

## 14. Cost/call ceiling

Default Layer 2 run = the 24-scenario dataset = 24 provider calls
expected, **≤48 worst case** (every call needing its one allowed retry,
§6). No repeated sampling, no background loops, no automatic run on
every PR — `real_llm` stays excluded from all three CI jobs (`Quality`,
`Tests`, `Tool Validation`), unchanged from Batch 22. The runner tracks
its own call count and raises a hard error if it ever exceeds
`len(dataset) * max_attempts` — a statically computable ceiling, a
defensive backstop against a future bug causing runaway calls, never an
approximate limit.

## 15. Fake-adapter testing (offline, unit-level, unchanged pattern)

A `FakeIntentInterpreter` (defined inside the relevant test file, never
importable from `src/`, per the existing `iac_agent.intent` fakes-in-
tests convention already used throughout Batch 21) covers: successful
intent, clarification-triggering intent, unsupported intent, each typed
`IntentInterpreterError` subtype, and malformed-payload handling via
`parse_intent_payload` directly. Real provider calls belong only under
`real_llm` — this offline coverage requires no network and no
credentials, exactly as today.

## 16. Dependency strategy

`pyproject.toml` currently has one extras group (`dev`). This design
adds, at implementation time, one independent new group:
`[project.optional-dependencies] openai = ["openai>=<pinned floor>,<next major>"]`
— `pip install -e .` (bare) never pulls in the SDK; only
`pip install -e ".[openai]"` does. A user who never touches `real_llm`
is never forced to install or configure anything provider-related.
Future `anthropic`/`bedrock` extras groups follow the identical pattern
with zero redesign. No agent framework (LangChain, CrewAI, LlamaIndex)
is added; `langgraph` remains exactly where it already is, not
introduced here merely to make one provider call.

## 17. Future provider portability

Adding an Anthropic (or Bedrock) adapter later means, and only means:

- one new file, `adapters/anthropic.py` (or `adapters/bedrock.py`),
  implementing the unchanged `IntentInterpreterPort`;
- one new arm in `create_intent_interpreter`'s `match`;
- one new `IntentInterpreterProvider` enum member;
- one new optional extras group;
- its own credential-loading function (a second API key, or — for
  Bedrock — `boto3`'s own credential chain);
- its own adapter-level unit tests and its own `real_llm`
  provider-selection smoke coverage (`IAC_AGENT_LLM_PROVIDER=anthropic pytest -m real_llm`);
- documentation.

**Explicitly verified: none of this touches `ArchitectureIntent`,
`ArchitectureResolver`, `IntentResolutionService` semantics,
`IacRequestSpec`, the Terraform rendering/plan/policy pipeline,
`SecurityGate`, HITL, or `GitHubSourceControl`.** The entire
multi-provider surface lives in exactly two places: `iac_agent.app.config`/
`iac_agent.app.composition` (composition-time configuration and
wiring) and new sibling files under `iac_agent.intent.adapters/`
(concrete adapters) — neither of which any resolver/service/pipeline
code depends on beyond the already-existing, unchanged
`IntentInterpreterPort` type. The shared Layer 2 dataset and evaluator
(§10) require zero changes for a new provider — only the composition
call resolves to a different adapter.

## 18. Explicit non-goals (Batch 23 design)

Raw HCL generation, Terraform-copilot free-form generation, IAM
generation, security decisions by the LLM, an autonomous agent loop,
tool-calling agents, a multi-agent system, CrewAI, LangChain, a
ten-vendor provider-abstraction framework, a Bedrock migration, a second
LLM provider actually implemented this batch, a UI/chat layer,
deployment, `terraform apply`, GitHub automation redesign, CI redesign,
branch-protection changes, a production telemetry platform, and a
prompt-persistence system are all explicitly out of scope.

## 19. Self-review against Batch 21 invariants

- [x] The LLM cannot create `IacRequestSpec` directly — the adapter's
      only output is `ArchitectureIntent`, validated locally.
- [x] The LLM cannot select an authoritative AWS architecture — the
      resolver allowlist is never disclosed to it, and
      `user_provided_hints` remains non-authoritative (unchanged
      resolver match keys: `workload_type`/`interaction_pattern`/
      `capabilities` only).
- [x] Local Pydantic validation (`parse_intent_payload`) remains
      authoritative regardless of provider-side schema enforcement.
- [x] `ArchitectureResolver` remains pure and deterministic — untouched.
- [x] `user_provided_hints` remain inert — unchanged resolver behavior,
      re-verified.
- [x] `confidence` remains non-authoritative — excluded from Layer 2
      PASS/FAIL by explicit design (§11), matching the resolver's own
      mechanically-proven invariant.
- [x] Raw prompts are not persisted by default — re-verified directly
      against `service.py`; the adapter upholds the identical rule.
- [x] `real_llm` remains excluded from ordinary CI — no workflow in
      Batch 22 sets `IAC_AGENT_LLM_PROVIDER`, and this design adds no
      new CI job.
- [x] No credential is introduced into the repository itself — API keys
      are environment-only, never written to any tracked file, dataset,
      or checkpoint.
- [x] No Terraform/security/HITL authority moves to the LLM — none of
      those modules are touched or referenced by any new file.
- [x] A second provider could be added without any domain change — see
      §17's explicit verification.

## 20. Unresolved questions for human review

1. **Exact `openai` SDK version floor/ceiling** — deferred to
   implementation time, when the actually-available SDK version can be
   checked directly rather than guessed now.
2. **Exact adapter-level "lowest-variance" parameter value** for the
   configured model — an implementation-time detail per §5, verified
   against whatever concrete model is configured at that time.
3. **The real acceptance run's outcome** — §13's triage process is
   designed now; its first real application (does `gpt-5-nano` in fact
   pass all 24 scenarios, all 5 of them hard requirements) is
   necessarily unknown until implementation.

None of these block review of the architecture itself — they are
implementation-time facts the design does not need to pre-answer.

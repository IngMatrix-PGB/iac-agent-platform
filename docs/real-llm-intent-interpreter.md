# Real LLM intent interpreter

`iac_agent.intent.service.IntentResolutionService` can be backed by a
real language model instead of the test-only `FakeIntentInterpreter`.
The model only fills a validated `ArchitectureIntent`. It does not
select Terraform resources, write IAM, or make a security or approval
decision. The resolver contract is `docs/intent.md`.

## Provider and model selection

```bash
export IAC_AGENT_LLM_PROVIDER=openai
export IAC_AGENT_LLM_MODEL=gpt-5-nano   # a documented starting point, not a requirement
```

Both are required, provider-neutral configuration — there is no silent
default for either. An unrecognized provider fails closed immediately.
`openai` is the only supported provider today; a future provider
(Anthropic, Bedrock) would be selected the same way, with no change to
`ArchitectureIntent`, `ArchitectureResolver`, or `IntentResolutionService`.

## Installing the OpenAI adapter (optional)

The `openai` SDK is an **optional** dependency — a bare
`pip install -e .` never installs it:

```bash
pip install -e ".[openai]"
```

## Credentials

```bash
export OPENAI_API_KEY=...
```

Required only when actually invoking the real adapter — never for
ordinary development, `ruff`, the deterministic test suite, or any CI
job. The key is never written to any file this project tracks, never
logged, and never appears in `ArchitectureIntent`, `IntentInterpreterConfig`,
or any persisted state.

## Running the Layer 2 real-model evaluation

```bash
IAC_AGENT_LLM_PROVIDER=openai IAC_AGENT_LLM_MODEL=gpt-5-nano \
  OPENAI_API_KEY=... pytest -m real_llm
```

This makes real network calls to OpenAI and consumes real tokens.
Pull-request CI still excludes the `real_llm` marker and does not set
`IAC_AGENT_LLM_PROVIDER`. A human measures the golden set by dispatching
the Intent regression workflow (`.github/workflows/intent-regression.yml`).
That workflow is `workflow_dispatch` only. The golden dataset has 26
scenarios, so a complete run makes 26 interpreter invocations and 26
provider attempts, or 52 provider attempts when every invocation uses
its one transient retry.

## Privacy

Raw natural-language prompts and raw provider responses are never
persisted or logged, by default, anywhere in this project. Only
metadata is recorded: a request ID, the provider and model name, a
prompt-contract version, latency, attempt count, and an outcome
category — never the request or response content itself.

## Adding a future provider

Implementing a second provider (Anthropic, Bedrock, or another) means,
and only means: one new adapter file under `src/iac_agent/intent/adapters/`,
one new member on `IntentInterpreterProvider`, one new arm in
`iac_agent.app.composition.create_intent_interpreter`, one new optional
extras group, and that provider's own credential loader. None of this
requires any change to `ArchitectureIntent`, `ArchitectureResolver`,
`IntentResolutionService`, or the existing Terraform/security/HITL
pipeline — this project does not implement a second provider yet.

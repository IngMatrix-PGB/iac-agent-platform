"""Layer 2 real-model eval — activated (Batch 23, Task 9).

This is the **only** file in the whole codebase allowed to call
`create_intent_interpreter` with a real, unfaked provider client. It
still makes **zero** real calls unless both of the following are true:
`IAC_AGENT_LLM_PROVIDER` is set (the `real_llm` marker's own
skip-gate) *and* the test is explicitly selected with
`pytest -m real_llm`. Ordinary `pytest`/`Quality`/`Tests`/`Tool
Validation` never sets `IAC_AGENT_LLM_PROVIDER`, so this test always
skips under every normal invocation.
"""

from __future__ import annotations

import os

import pytest

from evals.scenarios.architecture_intent_nl_runner import (
    format_summary,
    run_architecture_intent_nl_evals,
)
from iac_agent.app.composition import create_intent_interpreter
from iac_agent.app.config import (
    load_intent_interpreter_config_from_env,
    load_openai_api_key_from_env,
)

pytestmark = pytest.mark.real_llm


@pytest.mark.skipif(
    os.environ.get("IAC_AGENT_LLM_PROVIDER") is None,
    reason="no real LLM provider configured (IAC_AGENT_LLM_PROVIDER unset)",
)
def test_natural_language_to_intent_real_model_eval():
    config = load_intent_interpreter_config_from_env()
    # OPENAI is the only configured provider this batch supports; a
    # future second provider would need its own credential loader,
    # selected the same way `create_intent_interpreter` selects the
    # adapter itself.
    api_key = load_openai_api_key_from_env()
    interpreter = create_intent_interpreter(config, api_key=api_key)

    suite = run_architecture_intent_nl_evals(interpreter=interpreter)
    print("\n" + format_summary(suite, title="Architecture Intent NL Golden Evals (Layer 2)"))

    assert suite.failed == 0
    assert suite.errored == 0

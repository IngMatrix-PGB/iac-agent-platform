"""Layer 2 real-model eval foundation (Batch 21, Task 7, spec §15.2).

This is a minimal, inert foundation only — no real model call, no
provider SDK, no new dependency. It exists solely to prove the
`real_llm` marker/skip-gate mechanism, mirroring `real_tool`'s own
`shutil.which(...) is None` skip-gate shape exactly. `IAC_AGENT_LLM_PROVIDER`
is a new env var introduced purely as a test-collection gate — it is
not read by any production code this batch.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.real_llm


@pytest.mark.skipif(
    os.environ.get("IAC_AGENT_LLM_PROVIDER") is None,
    reason="no real LLM provider configured (IAC_AGENT_LLM_PROVIDER unset)",
)
def test_natural_language_to_intent_real_model_eval_placeholder():
    pytest.skip("Layer 2 real-model eval not implemented this batch — see spec §15.2, §22.1")

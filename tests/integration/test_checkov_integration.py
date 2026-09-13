"""Integration proof: the real Checkov CLI against Python-renderer output.

SQSResourceSpec -> TerraformCompositionRenderer -> write_to(tmp_path) ->
CheckovAdapter.scan(tmp_path) -> CheckovScanResult, using the real,
locally installed Checkov binary — never the manually-authored Batch 3
fixture.

This test does not assert an exact pass/fail count in advance: it runs
the real scanner and reports whatever it actually finds. If Checkov
flags something in the trusted module, that is real information to
report, not something to suppress to make this test green.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter, CheckovScanResult

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = pytest.mark.skipif(
    shutil.which("checkov") is None,
    reason="checkov binary not available on PATH",
)


def test_checkov_scans_real_renderer_output(tmp_path):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    result = CheckovAdapter().scan(tmp_path)

    assert isinstance(result, CheckovScanResult)
    # A scan that actually ran must always report internally consistent
    # counts — this is the property under test, not a specific number.
    assert result.passed_checks >= 0
    assert result.failed_checks == len(result.findings)
    assert all(f.resource is None or "/Users" not in f.resource for f in result.findings)
    assert all("/Users" not in f.message for f in result.findings)

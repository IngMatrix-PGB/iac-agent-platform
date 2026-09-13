"""Integration proof: Python renderer output -> trusted module -> real
Terraform plan.

This deliberately exercises the OUTPUT OF `TerraformCompositionRenderer`,
not the hand-authored Batch 3 fixture under tests/terraform/sqs/ — that
fixture remains separately valuable evidence that the trusted module
itself is sound, independent of the Python renderer. This test proves
the full chain: validated SQSResourceSpec -> generated composition ->
trusted module -> terraform fmt/init/validate/plan, entirely without
real AWS credentials.

Terraform commands are invoked directly here as a test-only harness.
No TerraformRunner abstraction exists yet (that is a later batch) and
the renderer itself (src/iac_agent/providers/aws/sqs/renderer.py)
contains no subprocess code at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None,
    reason="terraform binary not available on PATH",
)


def _clean_env() -> dict[str, str]:
    """A minimal environment with no ambient AWS configuration at all,
    regardless of what the host running this test may have set up —
    the credential-free claim must hold independent of the host."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    return env


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_renderer_output_produces_a_valid_credential_free_plan(tmp_path):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )

    # The module source must resolve correctly from THIS test workspace
    # (tmp_path), which sits at a different depth than the production
    # artifacts/<request_id>/ convention — so it is computed explicitly
    # here rather than relying on the renderer's DEFAULT_MODULE_SOURCE.
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)

    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    assert (tmp_path / "main.tf").exists()
    assert (tmp_path / "versions.tf").exists()

    env = _clean_env()

    fmt_check = _run(["terraform", "fmt", "-check"], cwd=tmp_path, env=env)
    assert fmt_check.returncode == 0, (
        "renderer output is not canonically formatted:\n"
        f"stdout={fmt_check.stdout}\nstderr={fmt_check.stderr}"
    )

    init = _run(["terraform", "init", "-backend=false"], cwd=tmp_path, env=env)
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    validate = _run(["terraform", "validate"], cwd=tmp_path, env=env)
    assert validate.returncode == 0, (
        f"terraform validate failed:\n{validate.stdout}\n{validate.stderr}"
    )

    plan_env = {**env, "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"}
    plan = _run(
        ["terraform", "plan", "-out=tfplan"],
        cwd=tmp_path,
        env=plan_env,
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"
    assert "2 to add, 0 to change, 0 to destroy" in plan.stdout

    show = _run(["terraform", "show", "-json", "tfplan"], cwd=tmp_path, env=env)
    assert show.returncode == 0, f"terraform show -json failed:\n{show.stderr}"

    plan_json = json.loads(show.stdout)
    resource_changes = {
        rc["address"]: rc["change"]["actions"] for rc in plan_json["resource_changes"]
    }

    assert resource_changes == {
        "module.queue.aws_sqs_queue.this": ["create"],
        "module.queue.aws_sqs_queue.dlq[0]": ["create"],
    }
    assert not any("delete" in actions for actions in resource_changes.values())

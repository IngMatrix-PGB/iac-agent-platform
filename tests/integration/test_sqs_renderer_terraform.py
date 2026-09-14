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

Batch 16.5: environment construction now goes through the shared
`terraform_test_env`/`terraform_plan_env_overrides` fixtures
(tests/integration/conftest.py) rather than a locally defined
`_clean_env()`, so `terraform init` here reuses the session-scoped
`TF_PLUGIN_CACHE_DIR` instead of downloading its own copy of the AWS
provider binary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec, derive_dlq_name
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_MODULE_DIR = _REPO_ROOT / "terraform" / "modules" / "sqs"

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None,
        reason="terraform binary not available on PATH",
    ),
]


def _run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_renderer_output_produces_a_valid_credential_free_plan(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
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

    env = terraform_test_env

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

    plan = _run(
        ["terraform", "plan", "-out=tfplan"],
        cwd=tmp_path,
        env=terraform_plan_env_overrides,
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


def test_renderer_output_with_multiple_differently_sized_tag_keys_is_canonically_formatted(
    tmp_path, terraform_test_env
):
    """Regression test for a real bug found by the Batch 15 live smoke:
    every prior real-`terraform fmt` test here used at most one tag, so
    the renderer's tag-map "=" alignment was never actually exercised
    against real `terraform fmt` with two-or-more differently-sized
    keys — see the fix and unit tests in
    tests/unit/providers/aws/sqs/test_renderer.py."""
    spec = SQSResourceSpec(
        name="iac-agent-phase1-demo",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"ManagedBy": "iac-agent-platform", "Purpose": "phase1-live-smoke"},
    )
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    fmt_check = _run(["terraform", "fmt", "-check", "-diff"], cwd=tmp_path, env=terraform_test_env)
    assert fmt_check.returncode == 0, (
        "renderer output with multi-tag map is not canonically formatted:\n"
        f"stdout={fmt_check.stdout}\nstderr={fmt_check.stderr}"
    )


# ---------------------------------------------------------------------------
# Batch 12.5 — cross-layer derived DLQ name proof
#
# Proves that Python's derive_dlq_name() and the trusted module's actual
# planned aws_sqs_queue.dlq name agree exactly, for a real boundary-valid
# spec of each queue type — not merely that both independently claim to
# implement "the same" derivation.
# ---------------------------------------------------------------------------


def _planned_dlq_name(
    spec: SQSResourceSpec,
    tmp_path: Path,
    terraform_test_env: dict[str, str],
    terraform_plan_env_overrides: dict[str, str],
) -> str:
    module_source = os.path.relpath(_TRUSTED_MODULE_DIR, start=tmp_path)
    composition = TerraformCompositionRenderer().render(spec, module_source=module_source)
    composition.write_to(tmp_path)

    env = terraform_test_env
    init = _run(["terraform", "init", "-backend=false"], cwd=tmp_path, env=env)
    assert init.returncode == 0, f"terraform init failed:\n{init.stdout}\n{init.stderr}"

    plan = _run(
        ["terraform", "plan", "-out=tfplan"], cwd=tmp_path, env=terraform_plan_env_overrides
    )
    assert plan.returncode == 0, f"terraform plan failed:\n{plan.stdout}\n{plan.stderr}"

    show = _run(["terraform", "show", "-json", "tfplan"], cwd=tmp_path, env=env)
    assert show.returncode == 0, f"terraform show -json failed:\n{show.stderr}"

    plan_json = json.loads(show.stdout)
    for resource_change in plan_json["resource_changes"]:
        if resource_change["address"] == "module.queue.aws_sqs_queue.dlq[0]":
            return resource_change["change"]["after"]["name"]
    raise AssertionError("no module.queue.aws_sqs_queue.dlq[0] in plan resource_changes")


def test_planned_dlq_name_matches_derive_dlq_name_for_standard_queue(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    name = "a" * 76  # boundary-valid: derived length is exactly 80
    spec = SQSResourceSpec(name=name)

    planned_name = _planned_dlq_name(
        spec, tmp_path, terraform_test_env, terraform_plan_env_overrides
    )

    assert planned_name == derive_dlq_name(spec.name, spec.fifo)


def test_planned_dlq_name_matches_derive_dlq_name_for_fifo_queue(
    tmp_path, terraform_test_env, terraform_plan_env_overrides
):
    name = "a" * 71 + ".fifo"  # boundary-valid: derived length is exactly 80
    spec = SQSResourceSpec(name=name, fifo=True)

    planned_name = _planned_dlq_name(
        spec, tmp_path, terraform_test_env, terraform_plan_env_overrides
    )

    assert planned_name == derive_dlq_name(spec.name, spec.fifo)

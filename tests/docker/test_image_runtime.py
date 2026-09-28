"""Gate A checks for the local runtime image. Requires a Docker daemon."""

from __future__ import annotations

import json
import subprocess
import time

import pytest

IMAGE = "iac-agent-platform:batch30"
HEALTH_NAME = "iac-agent-batch30-gate-a-health"
SECRET_MARKERS = ("sk-", "ghp_", "github_pat_", "AKIA")
PLACEHOLDER_ENV = [
    "GITHUB_OWNER=test",
    "GITHUB_REPOSITORY=test",
    "GITHUB_COMMIT_AUTHOR_NAME=test",
    "GITHUB_COMMIT_AUTHOR_EMAIL=test@example.com",
    "GITHUB_TOKEN=test",
    "IAC_AGENT_LLM_PROVIDER=openai",
    "IAC_AGENT_LLM_MODEL=test",
    "OPENAI_API_KEY=test",
    "IAC_AGENT_OBSERVABILITY=off",
]

pytestmark = pytest.mark.docker


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True)


@pytest.fixture(scope="module")
def image() -> str:
    result = _run(["docker", "build", "-t", IMAGE, "."])
    assert result.returncode == 0, result.stdout + result.stderr
    return IMAGE


def test_image_user_and_history_have_no_secrets(image: str) -> None:
    inspected = _run(["docker", "image", "inspect", image])
    history = _run(["docker", "history", "--no-trunc", image])
    assert inspected.returncode == 0, inspected.stderr
    assert history.returncode == 0, history.stderr
    payload = json.loads(inspected.stdout)[0]
    user = str(payload["Config"]["User"])
    assert user in {"iac", "10001", "iac:iac", "10001:10001"}
    blob = inspected.stdout + history.stdout
    for marker in SECRET_MARKERS:
        assert marker not in blob


def test_runtime_identity_versions_and_permissions(image: str) -> None:
    identity = _run(["docker", "run", "--rm", "--entrypoint", "id", image, "-u"])
    assert identity.returncode == 0, identity.stderr
    assert identity.stdout.strip() == "10001"

    python = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            image,
            "-c",
            "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
        ]
    )
    assert python.returncode == 0, python.stderr
    assert python.stdout.strip() == "3.12"

    terraform = _run(["docker", "run", "--rm", "--entrypoint", "terraform", image, "version"])
    assert terraform.returncode == 0, terraform.stderr
    assert "Terraform v1.16.1" in terraform.stdout

    checkov = _run(["docker", "run", "--rm", "--entrypoint", "checkov", image, "--version"])
    assert checkov.returncode == 0, checkov.stderr
    assert "3.3.13" in checkov.stdout

    permissions = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            image,
            "-c",
            (
                "import os, shutil\n"
                "writable = ['/var/lib/iac-agent/state', '/var/lib/iac-agent/workspaces',"
                " '/home/iac', '/tmp']\n"
                "frozen = ['/opt/iac-agent', '/opt/iac-agent/src',"
                " '/opt/iac-agent/terraform/modules', '/opt/checkov',"
                " '/opt/terraform/providers', os.path.dirname(shutil.which('terraform')),"
                " shutil.which('terraform')]\n"
                "bad = [p for p in writable if not os.access(p, os.W_OK)]\n"
                "open_ = [p for p in frozen if os.access(p, os.W_OK)]\n"
                "assert not bad, bad\n"
                "assert not open_, open_\n"
            ),
        ]
    )
    assert permissions.returncode == 0, permissions.stdout + permissions.stderr


def test_import_does_not_load_langfuse_when_observability_is_unset(image: str) -> None:
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            image,
            "-c",
            (
                "import os, sys\n"
                "os.environ.pop('IAC_AGENT_OBSERVABILITY', None)\n"
                "import iac_agent.api.app\n"
                "assert 'langfuse' not in sys.modules\n"
            ),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_init_uses_the_prepared_aws_provider(image: str) -> None:
    script = r"""
set -eu
mkdir -p /var/lib/iac-agent/workspaces/offline-init
cd /var/lib/iac-agent/workspaces/offline-init
cat > versions.tf <<'EOF'
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
EOF
terraform init -backend=false -input=false
"""
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            script,
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "registry.terraform.io" not in result.stderr


def test_offline_credential_free_plan(image: str) -> None:
    script = """
import os
from pathlib import Path

from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer

workspace = Path("/var/lib/iac-agent/workspaces/credential-free-plan")
workspace.mkdir(parents=True, exist_ok=True)
module = Path("/opt/iac-agent/terraform/modules/sqs")
spec = SQSResourceSpec(
    name="order-events",
    dlq=DlqSpec(enabled=True, max_receive_count=5),
    tags={"Service": "orders"},
)
source = os.path.relpath(module, start=workspace)
TerraformCompositionRenderer().render(spec, module_source=source).write_to(workspace)
runner = TerraformRunner()
runner.init(workspace)
runner.validate(workspace)
planned = runner.plan(
    workspace,
    env_overrides={"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test"},
)
assert "registry.terraform.io" not in planned.stderr
"""
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            image,
            "-c",
            script,
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_network_disabled_health_and_ready(image: str) -> None:
    _run(["docker", "rm", "-f", HEALTH_NAME])
    env = [item for pair in PLACEHOLDER_ENV for item in ("-e", pair)]
    started = _run(
        ["docker", "run", "-d", "--name", HEALTH_NAME, "--network", "none", *env, image]
    )
    try:
        assert started.returncode == 0, started.stderr
        deadline = time.monotonic() + 30
        health = ready = None
        while time.monotonic() < deadline:
            health = _run(
                [
                    "docker",
                    "exec",
                    HEALTH_NAME,
                    "/opt/iac-agent/.venv/bin/python",
                    "-c",
                    "import urllib.request; print(urllib.request.urlopen("
                    "'http://127.0.0.1:8000/health').status)",
                ]
            )
            if health.returncode == 0 and health.stdout.strip() == "200":
                ready = _run(
                    [
                        "docker",
                        "exec",
                        HEALTH_NAME,
                        "/opt/iac-agent/.venv/bin/python",
                        "-c",
                        "import urllib.request; print(urllib.request.urlopen("
                        "'http://127.0.0.1:8000/ready').status)",
                    ]
                )
                break
            time.sleep(1)
        logs = _run(["docker", "logs", HEALTH_NAME])
        assert health is not None and health.returncode == 0, logs.stdout + logs.stderr
        assert health.stdout.strip() == "200"
        assert ready is not None and ready.returncode == 0, logs.stdout + logs.stderr
        assert ready.stdout.strip() == "200"
    finally:
        _run(["docker", "rm", "-f", HEALTH_NAME])


def test_trusted_modules_resolve_under_the_image_root(image: str) -> None:
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/opt/iac-agent/.venv/bin/python",
            image,
            "-c",
            (
                "from pathlib import Path\n"
                "from iac_agent.domain.resource import ResourceType\n"
                "from iac_agent.graph.modules import trusted_module_dirs\n"
                "dirs = trusted_module_dirs(Path('/opt/iac-agent'))\n"
                "assert dirs[ResourceType.SQS].is_dir()\n"
                "assert dirs[ResourceType.ECR] == Path("
                "'/opt/iac-agent/terraform/modules/ecr').resolve()\n"
            ),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

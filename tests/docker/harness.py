"""Server used only by the Gate B container-replacement test.

Bind-mounted into the production image. It does not import GitHub and
does not add a production switch that disables OpenAI.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from iac_agent.api.app import create_app
from iac_agent.app.composition import IntentApplication
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.modules import default_trusted_module_dirs
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.intent.port import parse_intent_payload
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService
from iac_agent.observability.noop import NoOpObservability
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.security.checkov import CheckovAdapter

_WORKER_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "worker",
    "interaction_pattern": "asynchronous",
    "capabilities": ["queue_processing", "persistence"],
}
_CALLS = Path("/var/lib/iac-agent/state/publisher-calls")
_PR_URL = "https://example.invalid/pull/7"


class _WorkerInterpreter:
    def interpret(self, *, natural_language_request: str, request_id: str):
        return parse_intent_payload(_WORKER_PAYLOAD)


class _RaisingInterpreter:
    def interpret(self, *, natural_language_request: str, request_id: str):
        raise AssertionError("replacement container must not reinterpret the request")


class _VolumePublisher:
    def __init__(self) -> None:
        self._start = int(_CALLS.read_text()) if _CALLS.exists() else 0
        self.calls = 0

    def publish_change(self, **kwargs):
        self.calls += 1
        _CALLS.write_text(str(self._start + self.calls))
        return PullRequestResult(
            number=7,
            url=_PR_URL,
            branch="iac-agent/req-docker-fresh",
            base_branch="main",
        )


def main() -> None:
    state_db = Path(os.environ["IAC_AGENT_STATE_DB"])
    workspace_root = Path(os.environ["IAC_AGENT_WORKSPACE_ROOT"])
    role = os.environ.get("IAC_AGENT_HARNESS_ROLE", "a")
    interpreter = _RaisingInterpreter() if role == "b" else _WorkerInterpreter()
    observability = NoOpObservability()
    with open_sqlite_checkpointer(state_db) as saver:
        graph = build_iac_workflow(
            renderer=AWSResourceRenderer(),
            terraform_runner=TerraformRunner(),
            checkov_adapter=CheckovAdapter(),
            source_control_port=_VolumePublisher(),
            workspace_root=workspace_root,
            trusted_module_dirs=default_trusted_module_dirs(),
            checkpointer=saver,
        )
        config = ApplicationConfig(
            workspace_root=workspace_root,
            state_db_path=state_db,
            github_owner="example-user",
            github_repository="iac-agent-platform",
            github_commit_author_name="Example Bot",
            github_commit_author_email="example-bot@example.invalid",
        )
        application = IacApplication(graph, observability=observability)
        service = IntentResolutionService(
            interpreter=interpreter,
            resolver=ArchitectureResolver(),
            application=application,
            observability=observability,
        )
        holder = IntentApplication(
            config=config, intent_service=service, application=application
        )
        uvicorn.run(create_app(holder), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()

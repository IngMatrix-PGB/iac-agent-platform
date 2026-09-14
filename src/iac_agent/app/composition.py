"""Application composition root (Batch 15).

`open_application` is the one place Phase 1's real adapters (the
Terraform renderer, `TerraformRunner`, `CheckovAdapter`,
`GitHubSourceControl`, the SQLite checkpointer) are constructed and
wired into the compiled LangGraph workflow. No domain module or graph
node constructs any of these itself, and none of them reads
`os.environ` — see `iac_agent.app.config`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from iac_agent.app.config import ApplicationConfig
from iac_agent.domain.source_control import GitCommitIdentity
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.git.github import GitHubRepository, GitHubSourceControl, HttpTransport
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter


@dataclass(frozen=True)
class Application:
    """Everything a caller (a future FastAPI/CLI layer, `Phase1Application`,
    or a one-off script) needs to run the Phase 1 workflow.

    Deliberately does not hold the GitHub token, the raw SQLite
    connection, or anything else construction-complexity-shaped — only
    the config it was built from and the ready-to-invoke compiled graph.
    """

    config: ApplicationConfig
    graph: CompiledStateGraph


@contextmanager
def open_application(
    config: ApplicationConfig,
    *,
    github_token: SecretStr,
    github_transport: HttpTransport | None = None,
) -> Iterator[Application]:
    """Construct the real Phase 1 adapters and compiled graph, and
    guarantee the underlying SQLite connection is closed on exit — even
    on error.

    `github_token` is unwrapped only at the point of constructing
    `GitHubSourceControl` — it is never stored on `Application`, never
    written into `ApplicationConfig`, and never logged.

    `github_transport` defaults to `None`, meaning `GitHubSourceControl`
    uses its real `UrllibHttpTransport` — this parameter exists only so
    tests can inject a fake transport through the same composition path
    production code uses, rather than duplicating the wiring.
    """
    config.state_db_path.parent.mkdir(parents=True, exist_ok=True)

    with open_sqlite_checkpointer(config.state_db_path) as saver:
        source_control_port = GitHubSourceControl(
            repository=GitHubRepository(owner=config.github_owner, name=config.github_repository),
            token=github_token.get_secret_value(),
            commit_identity=GitCommitIdentity(
                name=config.github_commit_author_name, email=config.github_commit_author_email
            ),
            transport=github_transport,
        )
        graph = build_sqs_workflow(
            renderer=TerraformCompositionRenderer(),
            terraform_runner=TerraformRunner(),
            checkov_adapter=CheckovAdapter(),
            source_control_port=source_control_port,
            workspace_root=config.workspace_root,
            trusted_module_dir=config.terraform_module_path,
            base_branch=config.github_base_branch,
            checkpointer=saver,
        )
        yield Application(config=config, graph=graph)

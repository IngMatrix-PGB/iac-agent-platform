"""Application composition root (Batch 15).

`open_application` is the one place Phase 1's real adapters (the
Terraform renderer, `TerraformRunner`, `CheckovAdapter`,
`GitHubSourceControl`, the SQLite checkpointer) are constructed and
wired into the compiled LangGraph workflow. No domain module or graph
node constructs any of these itself, and none of them reads
`os.environ` — see `iac_agent.app.config`.

Batch 20 stopped passing an explicit `trusted_module_dir=` to
`build_sqs_workflow` — the value it used to pass
(`ApplicationConfig.terraform_module_path`, now removed) was always
identical to `build_sqs_workflow`'s own default, so this is a pure
simplification, not a behavior change. This composition root still
needed **zero** other changes to support `ServerlessWorkerSpec` (Batch
19) or `ApiLambdaSpec` (Batch 20) requests: `build_sqs_workflow` is a
thin wrapper around the fully request-generalized `build_iac_workflow`,
whose own defaults (`_DEFAULT_TRUSTED_MODULE_DIRS`, a default-
constructed `ServerlessWorkerTerraformRenderer`/`ApiLambdaTerraformRenderer`)
already cover every resource and composition type this platform
supports — see `tests/integration/test_application_composition.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from iac_agent.app.config import (
    ApplicationConfig,
    IntentInterpreterConfig,
    IntentInterpreterProvider,
)
from iac_agent.domain.source_control import GitCommitIdentity
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.git.github import GitHubRepository, GitHubSourceControl, HttpTransport
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.intent.port import IntentInterpreterPort
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
            base_branch=config.github_base_branch,
            checkpointer=saver,
        )
        yield Application(config=config, graph=graph)


def create_intent_interpreter(
    config: IntentInterpreterConfig, *, api_key: SecretStr
) -> IntentInterpreterPort:
    """The one place in this codebase that ever dispatches on provider
    identity (Batch 23). One arm today; a future provider (Anthropic,
    Bedrock) means one new `IntentInterpreterProvider` member and one
    new arm here — nothing else in the domain ever needs to know.

    The adapter import is deliberately **inside** this function, not at
    module scope: `iac_agent.app.composition` is imported unconditionally
    by every Terraform-pipeline caller of `open_application`, and the
    `openai` SDK is an optional dependency (`pip install -e ".[openai]"`)
    — a bare install must never fail to import this module.
    """
    match config.provider:
        case IntentInterpreterProvider.OPENAI:
            from iac_agent.intent.adapters.openai import OpenAIIntentInterpreter

            return OpenAIIntentInterpreter(model=config.model, api_key=api_key)

"""Batch 24, Task 3: `IntentApplication` composition holder proofs.

`IntentApplication` owns lifetime only — no propose/resume/submit
business methods. `open_intent_application` wraps the existing
`open_application` unchanged; this file proves the wiring identity
without invoking real Terraform (the inner `open_application` call is
patched)."""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr

import iac_agent.app.composition as mod
from iac_agent.app.composition import Application, IntentApplication, open_intent_application
from iac_agent.app.config import ApplicationConfig
from iac_agent.intent.resolver import ArchitectureResolver

_RESOLVABLE_API_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "api",
    "interaction_pattern": "synchronous",
    "capabilities": ["http_endpoint"],
}


class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload

    def interpret(self, *, natural_language_request, request_id):
        from iac_agent.intent.port import parse_intent_payload

        return parse_intent_payload(self._payload)


class FakeRenderer:
    def render(self, spec, *, module_source):
        from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition

        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )


class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult

        return CommandResult(("terraform", "fmt"), 0, "", "", 0.0)

    def init(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult

        return CommandResult(("terraform", "init"), 0, "", "", 0.0)

    def validate(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult

        return CommandResult(("terraform", "validate"), 0, "", "", 0.0)

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult

        return CommandResult(("terraform", "plan"), 0, "", "", 0.0)

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return {"resource_changes": []}


class FakeCheckovAdapter:
    def scan(self, workspace, *, profile=None):
        from iac_agent.security.checkov import CheckovScanResult

        return CheckovScanResult(
            findings=(), passed_checks=1, failed_checks=0, skipped_checks=0, scanner_version=None
        )


class FakeSourceControl:
    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


def _build_fake_graph(tmp_path):
    from iac_agent.graph.workflow import build_sqs_workflow

    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    return build_sqs_workflow(
        renderer=FakeRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=FakeSourceControl(),
        workspace_root=workspace_root,
        checkpointer=None,
    )


def test_intent_application_fields_are_exactly_config_service_application():
    assert {f.name for f in fields(IntentApplication)} == {
        "config",
        "intent_service",
        "application",
    }
    assert not callable(getattr(IntentApplication, "propose", None))
    assert not callable(getattr(IntentApplication, "resume", None))
    assert not callable(getattr(IntentApplication, "submit", None))


def test_open_intent_application_wires_same_iac_application_instance(tmp_path):
    config = ApplicationConfig(
        workspace_root=tmp_path / "workspaces",
        state_db_path=tmp_path / "state.db",
        github_owner="example-user",
        github_repository="iac-agent-platform",
        github_commit_author_name="Example Bot",
        github_commit_author_email="example-bot@example.invalid",
    )
    graph = _build_fake_graph(tmp_path)
    inner = Application(config=config, graph=graph)

    interpreter = FakeIntentInterpreter(payload=_RESOLVABLE_API_PAYLOAD)

    with patch("iac_agent.app.composition.open_application") as mocked:
        mocked.return_value.__enter__.return_value = inner
        mocked.return_value.__exit__.return_value = False
        with open_intent_application(
            config,
            github_token=SecretStr("fake-test-token-not-real"),
            interpreter=interpreter,
            github_transport=object(),
        ) as holder:
            assert holder.config is config
            assert holder.application._graph is graph
            assert holder.intent_service._application is holder.application
            assert holder.intent_service._interpreter is interpreter
            assert isinstance(holder.intent_service._resolver, ArchitectureResolver)
            assert not hasattr(holder, "github_token")
            assert "fake-test-token-not-real" not in repr(holder)

    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["github_token"].get_secret_value() == "fake-test-token-not-real"
    assert kwargs["github_transport"] is not None


def test_open_application_signature_unchanged():
    from iac_agent.app.composition import open_application

    params = inspect.signature(open_application).parameters
    assert list(params) == ["config", "github_token", "github_transport"]


def test_composition_module_does_not_import_openai_at_module_level():
    # Only direct children of the Module node — mirrors
    # tests/unit/intent/test_multi_provider_boundary_isolation.py's own
    # `_module_level_import_names` exactly. `ast.walk` would also
    # recurse into `open_intent_application`'s body and defeat the
    # "module level" distinction this test exists to prove.
    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "openai" not in imported
    assert "iac_agent.intent.service" not in imported  # lazy, inside the function

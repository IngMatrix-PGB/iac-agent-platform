"""Composition opens request_index on the same state.db as the checkpointer."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from pydantic import SecretStr

from iac_agent.app.composition import Application, open_intent_application
from iac_agent.app.config import ApplicationConfig, ObservabilitySettings
from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.noop import NoOpObservability
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer
from iac_agent.persistence.request_index import open_request_index


class _Interpreter:
    def interpret(self, *, natural_language_request: str, request_id: str):
        raise AssertionError("composition wiring must not interpret")


def _config(tmp_path: Path) -> ApplicationConfig:
    return ApplicationConfig(
        workspace_root=tmp_path,
        state_db_path=tmp_path / "state.db",
        github_owner="example-user",
        github_repository="example-repo",
        github_commit_author_name="Example",
        github_commit_author_email="example@example.invalid",
    )


def test_composition_indexes_the_same_state_database(tmp_path, monkeypatch):
    config = _config(tmp_path)

    @contextmanager
    def fake_open(passed, **kwargs):
        del kwargs
        assert passed.state_db_path == config.state_db_path
        yield Application(config=passed, graph=object())

    monkeypatch.setattr("iac_agent.app.composition.open_application", fake_open)
    monkeypatch.setattr(
        "iac_agent.app.composition.load_observability_settings_from_env",
        lambda: ObservabilitySettings(),
    )
    monkeypatch.setattr(
        "iac_agent.app.composition.build_observability",
        lambda settings, **kwargs: FailOpenObservability(NoOpObservability()),
    )

    with open_intent_application(
        config, github_token=SecretStr("test"), interpreter=_Interpreter()
    ) as holder:
        assert holder.application._request_index is not None
        holder.application._request_index.record("req-wire")

    with open_sqlite_checkpointer(config.state_db_path) as saver:
        saver.setup()

    connection = sqlite3.connect(config.state_db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert "request_index" in tables
    assert "checkpoints" in tables

    with open_request_index(config.state_db_path) as index:
        assert index.newest(20) == (("req-wire", index.newest(20)[0][1]),)

    source = Path("src/iac_agent/persistence/request_index.py").read_text()
    assert "langfuse" not in source
    assert "openai" not in source
    assert "boto3" not in source

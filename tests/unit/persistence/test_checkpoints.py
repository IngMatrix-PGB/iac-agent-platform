"""Unit tests for the SQLite checkpoint persistence boundary.

No real workflow/graph execution here — these tests exercise only the
persistence adapter itself (path validation, thread-config mapping,
saver lifecycle). Round-trip/isolation/error-durability tests that
exercise this adapter together with the real graph live in
tests/unit/graph/test_workflow.py and
tests/integration/test_sqs_workflow_persistence.py.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from iac_agent.persistence import checkpoints as checkpoints_module
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config

# ---------------------------------------------------------------------------
# Persistence boundary
# ---------------------------------------------------------------------------


def test_explicit_db_path_is_required():
    with pytest.raises(TypeError):
        open_sqlite_checkpointer()  # type: ignore[call-arg]


def test_directory_passed_as_db_path_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="directory"):
        with open_sqlite_checkpointer(tmp_path):
            pass


def test_nonexistent_parent_directory_is_rejected(tmp_path):
    """Documented Batch 12 choice: a missing parent directory is
    rejected rather than silently created — the caller must create it
    explicitly."""
    missing_parent_path = tmp_path / "does-not-exist" / "checkpoints.sqlite3"
    with pytest.raises(ValueError, match="parent directory"):
        with open_sqlite_checkpointer(missing_parent_path):
            pass


def test_existing_parent_directory_with_new_db_file_is_accepted(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    with open_sqlite_checkpointer(db_path) as saver:
        assert isinstance(saver, SqliteSaver)
    assert db_path.exists()


def test_sqlite_imports_are_isolated_to_the_persistence_package():
    """No domain/provider/security/policy module may import sqlite3 or
    langgraph.checkpoint.sqlite directly."""
    import iac_agent.domain.plan as domain_plan
    import iac_agent.domain.security as domain_security
    import iac_agent.domain.workflow as domain_workflow
    import iac_agent.policies.platform as policies_platform
    import iac_agent.providers.aws.sqs.contract as sqs_contract
    import iac_agent.security.checkov as security_checkov
    import iac_agent.security.gate as security_gate

    forbidden_modules = {"sqlite3", "langgraph.checkpoint.sqlite"}
    for module in (
        domain_plan,
        domain_security,
        domain_workflow,
        policies_platform,
        sqs_contract,
        security_checkov,
        security_gate,
    ):
        tree = ast.parse(inspect.getsource(module))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        assert not (imported_modules & forbidden_modules), (module.__name__, imported_modules)


def test_saver_lifecycle_closes_the_underlying_connection_cleanly(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    captured_conn = None

    with open_sqlite_checkpointer(db_path) as saver:
        captured_conn = saver.conn

    with pytest.raises(Exception):  # noqa: B017 - sqlite3.ProgrammingError on a closed connection
        captured_conn.execute("select 1")


def test_saver_connection_is_closed_even_when_the_with_block_raises(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    captured_conn = None

    with pytest.raises(RuntimeError):
        with open_sqlite_checkpointer(db_path) as saver:
            captured_conn = saver.conn
            raise RuntimeError("simulated failure inside the with-block")

    with pytest.raises(Exception):  # noqa: B017
        captured_conn.execute("select 1")


# ---------------------------------------------------------------------------
# Thread configuration
# ---------------------------------------------------------------------------


def test_request_id_maps_deterministically_to_thread_id():
    config = workflow_config("req-001")
    assert config == {"configurable": {"thread_id": "req-001"}}


def test_same_request_id_gives_same_config():
    assert workflow_config("req-001") == workflow_config("req-001")


def test_different_request_ids_give_different_thread_ids():
    config_a = workflow_config("req-001")
    config_b = workflow_config("req-002")
    assert config_a["configurable"]["thread_id"] != config_b["configurable"]["thread_id"]


@pytest.mark.parametrize("bad_request_id", ["", "../escape", "/etc/passwd", "a/b"])
def test_invalid_request_id_is_rejected(bad_request_id):
    with pytest.raises(ValueError):
        workflow_config(bad_request_id)


def test_workflow_config_never_generates_a_uuid_or_timestamp():
    """The only value that can ever appear as thread_id is the exact
    request_id passed in — nothing is generated inside this helper.
    Checked via the module's actual import statements (not a substring
    search over docstrings/comments, which legitimately discuss this
    guarantee in prose)."""
    tree = ast.parse(inspect.getsource(checkpoints_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"uuid", "datetime", "time", "random"}
    assert not (imported_roots & forbidden), imported_roots & forbidden

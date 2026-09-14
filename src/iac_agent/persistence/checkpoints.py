"""SQLite-backed LangGraph checkpoint saver — the durable persistence
adapter boundary.

`open_sqlite_checkpointer` is the only factory this project uses to
obtain a durable checkpoint saver, and `workflow_config` is the only
place a LangGraph thread configuration is built. Both are deliberately
narrow: no repository framework, no registry, no dynamic backend
selection — Phase 1 needs exactly one thing, a working SQLite-backed
`BaseCheckpointSaver`.

The checkpoint serializer is configured with an explicit allowlist of
this project's own domain types (`allowed_msgpack_modules`) rather than
relying on `JsonPlusSerializer`'s permissive default (which allows any
unregistered type with a warning). This is deliberately a *narrower*
and safer configuration than the default — not an unsafe pickle
fallback (`pickle_fallback` is never set to `True` anywhere in this
project).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from iac_agent.domain.workflow import validate_request_id

#: Every custom domain type that can legitimately appear in
#: WorkflowState, as explicit (module, qualname) pairs. Deliberately
#: exhaustive and explicit rather than a module-level wildcard — the
#: underlying allowlist mechanism only matches exact (module, name)
#: pairs, and being exhaustive here is what makes this narrower than
#: the "allow anything with a warning" default.
_ALLOWED_WORKFLOW_TYPES: tuple[tuple[str, str], ...] = (
    ("iac_agent.providers.aws.sqs.contract", "SQSResourceSpec"),
    ("iac_agent.providers.aws.sqs.contract", "EncryptionSpec"),
    ("iac_agent.providers.aws.sqs.contract", "DlqSpec"),
    ("iac_agent.domain.plan", "PlanAction"),
    ("iac_agent.domain.plan", "ResourceChange"),
    ("iac_agent.domain.plan", "PlanSummary"),
    ("iac_agent.domain.security", "PolicyStatus"),
    ("iac_agent.domain.security", "SecuritySeverity"),
    ("iac_agent.domain.security", "FindingSource"),
    ("iac_agent.domain.security", "SecurityFinding"),
    ("iac_agent.domain.security", "PolicyEvaluation"),
    ("iac_agent.domain.security", "SecurityGateResult"),
    ("iac_agent.security.checkov", "CheckovScanResult"),
    ("iac_agent.domain.workflow", "WorkflowStatus"),
    ("iac_agent.domain.workflow", "WorkflowStage"),
    ("iac_agent.domain.workflow", "WorkflowError"),
    ("iac_agent.domain.approval", "ApprovalDecision"),
    ("iac_agent.domain.source_control", "PullRequestResult"),
)


def _build_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=list(_ALLOWED_WORKFLOW_TYPES))


def _validate_db_path(db_path: Path) -> None:
    if db_path.exists() and db_path.is_dir():
        raise ValueError(f"db_path must be a file path, not an existing directory: {db_path}")
    if not db_path.parent.exists():
        raise ValueError(
            f"parent directory of db_path does not exist: {db_path.parent} "
            "(create it explicitly before opening the checkpointer — this "
            "boundary never creates directories on the caller's behalf)"
        )


@contextmanager
def open_sqlite_checkpointer(db_path: Path) -> Iterator[SqliteSaver]:
    """Open a durable SQLite-backed LangGraph checkpoint saver at `db_path`.

    A context manager: the underlying SQLite connection is always
    closed on exit, even on error — no open handle is ever left behind.
    `db_path` must be an explicit path (no default location is ever
    assumed) whose parent directory already exists; it must not itself
    already exist as a directory.
    """
    _validate_db_path(db_path)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        yield SqliteSaver(conn, serde=_build_serializer())
    finally:
        conn.close()


def workflow_config(request_id: str) -> dict[str, dict[str, str]]:
    """The canonical LangGraph `RunnableConfig` for a workflow thread.

    `thread_id` is always exactly `request_id` — never a separately
    generated UUID or timestamp, and this helper gives no way for a
    caller to supply a different `thread_id` that could drift from the
    request identity. Uses the exact same `request_id` safety rule as
    the graph's workspace-path resolver.
    """
    validate_request_id(request_id)
    return {"configurable": {"thread_id": request_id}}

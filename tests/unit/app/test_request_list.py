"""List rows come from the index, then from checkpoint reads. Stale rows drop."""

from __future__ import annotations

from iac_agent.app.service import IacApplication
from iac_agent.domain.workflow import WorkflowStatus


class _Spec:
    def __init__(self, name: str) -> None:
        self.name = name


class _Gate:
    def __init__(self, status: str) -> None:
        self.overall_status = type("Status", (), {"value": status})()


class _Snapshot:
    def __init__(self, *, created_at, values) -> None:
        self.created_at = created_at
        self.values = values


class _Graph:
    def __init__(self, snapshots: dict[str, _Snapshot]) -> None:
        self.snapshots = snapshots
        self.reads: list[str] = []

    def get_state(self, config):
        request_id = config["configurable"]["thread_id"]
        self.reads.append(request_id)
        return self.snapshots[request_id]

    def invoke(self, payload, config):
        raise AssertionError("list_requests must not invoke the graph")


class _Index:
    def __init__(self, rows: tuple[tuple[str, str], ...]) -> None:
        self.rows = rows
        self.limits: list[int] = []
        self.records: list[str] = []

    def newest(self, limit: int) -> tuple[tuple[str, str], ...]:
        self.limits.append(limit)
        return self.rows[:limit]

    def record(self, request_id: str) -> None:
        self.records.append(request_id)


def _present(status: WorkflowStatus, *, name: str, security: str) -> _Snapshot:
    return _Snapshot(
        created_at="checkpoint",
        values={
            "workflow_status": status,
            "resource_spec": _Spec(name),
            "security_gate": _Gate(security),
        },
    )


def test_list_requests_projects_checkpoint_state_and_skips_stale_rows():
    index = _Index(
        (
            ("req-c", "2026-09-29T00:00:03.000000Z"),
            ("req-b", "2026-09-29T00:00:02.000000Z"),
            ("req-a", "2026-09-29T00:00:01.000000Z"),
        )
    )
    graph = _Graph(
        {
            "req-c": _present(WorkflowStatus.AWAITING_APPROVAL, name="orders", security="pass"),
            "req-b": _Snapshot(created_at=None, values={}),
            "req-a": _present(WorkflowStatus.BLOCKED, name="archive", security="block"),
        }
    )
    listed = IacApplication(graph, request_index=index).list_requests(limit=3)
    assert index.limits == [3]
    assert graph.reads == ["req-c", "req-b", "req-a"]
    assert index.records == []
    assert index.rows[1][0] == "req-b"
    assert [item.view.request_id for item in listed] == ["req-c", "req-a"]
    assert listed[0].created_at == "2026-09-29T00:00:03.000000Z"
    assert (listed[0].view.workflow_status is WorkflowStatus.AWAITING_APPROVAL) is True
    assert (listed[1].view.workflow_status is WorkflowStatus.AWAITING_APPROVAL) is False
    assert listed[0].view.security_status == "pass"
    assert listed[0].view.resource_name == "orders"
    assert listed[1].view.security_status == "block"
    assert listed[1].view.resource_name == "archive"
    assert all(item.view.workflow_status is not WorkflowStatus.PENDING for item in listed)
    assert "req-b" not in {item.view.request_id for item in listed}


def test_empty_index_returns_no_rows():
    index = _Index(())
    listed = IacApplication(_Graph({}), request_index=index).list_requests(limit=20)
    assert listed == ()
    assert index.limits == [20]

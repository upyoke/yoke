"""Focused tests for ``claims.work.holder_*`` handlers."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import claims_work_holders


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.work.holder_list",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class _KeepOpenConn:
    """Context-manager wrapper so the handler's ``with connect()`` block
    does not close the test's disposable connection."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


def test_holder_list_filters_by_session_id(monkeypatch) -> None:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        conn,
        "CREATE TABLE work_claims ("
        "id INTEGER, session_id TEXT, target_kind TEXT, item_id INTEGER, "
        "epic_id INTEGER, task_num INTEGER, process_key TEXT, "
        "conflict_group TEXT, claimed_at TEXT, last_heartbeat TEXT, "
        "released_at TEXT)",
    )
    for row in (
        (1, "held-a", 10, "2026-01-02T00:00:00Z", None),
        (2, "held-b", 11, "2026-01-03T00:00:00Z", None),
        (3, "held-a", 12, "2026-01-01T00:00:00Z", "done"),
    ):
        conn.execute(
            "INSERT INTO work_claims "
            "(id, session_id, target_kind, item_id, claimed_at, released_at) "
            "VALUES (%s, %s, 'item', %s, %s, %s)",
            row,
        )
    conn.commit()
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: _KeepOpenConn(conn),
    )
    monkeypatch.setattr(
        claims_work_holders,
        "_current_item_before_implementation",
        lambda _conn, _session_id: True,
    )

    outcome = claims_work_holders.handle_holder_list(
        _request({"session_id": "held-a"})
    )

    assert outcome.primary_success
    assert outcome.result_payload["current_item_before_implementation"] is True
    # This fixture carries claims but no lane table, so the lanes come
    # back empty rather than failing the lookup — the shape a caller
    # asking "which trees may this session verify in?" relies on.
    assert outcome.result_payload["holders"] == [
        {
            "claim_id": 1,
            "session_id": "held-a",
            "target_kind": "item",
            "item_id": 10,
            "epic_id": None,
            "task_num": None,
            "claimed_at": "2026-01-02T00:00:00Z",
            "last_heartbeat": None,
            "lane_worktrees": [],
        }
    ]


def _seeded_lane_db():
    """A universe with one active lane held by one live claim."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        conn,
        "CREATE TABLE work_claims ("
        "id INTEGER, session_id TEXT, target_kind TEXT, item_id INTEGER, "
        "epic_id INTEGER, task_num INTEGER, process_key TEXT, "
        "conflict_group TEXT, claimed_at TEXT, last_heartbeat TEXT, "
        "released_at TEXT)",
    )
    apply_fixture_ddl(
        conn,
        "CREATE TABLE item_worktrees ("
        "id INTEGER, item_id INTEGER, branch TEXT, path TEXT, "
        "lane_role TEXT, state TEXT, created_at TEXT, updated_at TEXT, "
        "released_at TEXT)",
    )
    conn.execute(
        "INSERT INTO work_claims "
        "(id, session_id, target_kind, item_id, claimed_at, released_at) "
        "VALUES (7, 'holding-session', 'item', 4242, "
        "'2026-01-02T00:00:00Z', NULL)"
    )
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id, item_id, branch, path, lane_role, state, created_at, "
        "updated_at, released_at) VALUES "
        "(3, 4242, 'held', '/repo/.worktrees/held', 'implementation', "
        "'active', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', NULL)"
    )
    conn.commit()
    return conn


def _path_request(path: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.work.holder_get",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload={"path": path},
    )


def test_holder_get_by_path_finds_the_lane_holder(monkeypatch) -> None:
    """A caller with a path and no item still learns who owns the tree."""
    conn = _seeded_lane_db()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = claims_work_holders.handle_holder_get(
        _path_request("/repo/.worktrees/held/src/a.py")
    )

    assert outcome.primary_success
    holder = outcome.result_payload["holder"]
    assert holder["session_id"] == "holding-session"
    assert holder["item_id"] == 4242
    assert holder["lane_worktrees"] == ["/repo/.worktrees/held"]


def test_holder_get_by_path_outside_any_lane_is_empty_not_an_error(
    monkeypatch,
) -> None:
    """No claimed lane contains it — that is the answer, not a failure."""
    conn = _seeded_lane_db()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = claims_work_holders.handle_holder_get(
        _path_request("/repo/runtime/api/a.py")
    )

    assert outcome.primary_success
    assert outcome.result_payload["holder"] is None


def test_holder_get_without_item_or_path_is_a_payload_error() -> None:
    outcome = claims_work_holders.handle_holder_get(
        FunctionCallRequest(
            function="claims.work.holder_get",
            actor=ActorContext(actor_id="1", session_id="caller"),
            target=TargetRef(kind="global"),
            payload={},
        )
    )
    assert not outcome.primary_success

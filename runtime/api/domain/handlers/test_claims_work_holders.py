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

    outcome = claims_work_holders.handle_holder_list(
        _request({"session_id": "held-a"})
    )

    assert outcome.primary_success
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
        }
    ]

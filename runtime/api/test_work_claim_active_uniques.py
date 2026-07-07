"""Regression coverage for active item + epic-task claim uniqueness."""

from __future__ import annotations

import contextlib
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import sessions_lifecycle_claim as claim_module
from yoke_core.domain.schema_init_work_claim_indexes import (
    ACTIVE_EPIC_TASK_INDEX_NAME,
    ACTIVE_ITEM_INDEX_NAME,
)
from yoke_core.domain.schema_common import _get_indexes
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.work_claim_targets import make_epic_task_target, make_item_target
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.test_sessions import _apply_on_backend, _create_schema, _register, conn  # noqa: F401  (Postgres-backed pytest fixture)


def _index_names(conn) -> set[str]:
    return set(_get_indexes(conn))


def _insert_claim(conn, session_id: str, target_kind: str, **target) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, epic_id, task_num, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, %s, %s, 'exclusive', %s, %s)",
        (
            session_id,
            target_kind,
            target.get("item_id"),
            target.get("epic_id"),
            target.get("task_num"),
            now,
            now,
        ),
    )


def _register_pair(conn) -> None:
    _register(conn, session_id="sess-A")
    _register(conn, session_id="sess-B")


def test_fresh_schema_creates_active_uniques(conn):
    names = _index_names(conn)
    assert ACTIVE_ITEM_INDEX_NAME in names
    assert ACTIVE_EPIC_TASK_INDEX_NAME in names


@pytest.mark.parametrize("claim_kwargs", [
    {"item_id": "YOK-777"}, {"target": make_epic_task_target(88, 2)},
])
def test_claim_work_translates_integrity_error_with_holder(
    monkeypatch,
    claim_kwargs,
    conn,
):
    _register_pair(conn)

    def fake_insert(conn, _session_id, target, _now_value):
        if target.kind == "item":
            _insert_claim(conn, "sess-A", "item", item_id=target.item_id)
        else:
            _insert_claim(
                conn, "sess-A", "epic_task",
                epic_id=target.epic_id, task_num=target.task_num,
            )
        # Commit the competing holder so it survives claim_work's
        # post-IntegrityError rollback on Postgres — a real unique-index
        # race winner is a committed row from another session, and the
        # rollback would otherwise discard an uncommitted same-connection
        # insert before _resolve_active_holder re-reads the holder.
        conn.commit()
        raise db_backend.integrity_error_types(conn)[0]("active claim unique constraint")

    monkeypatch.setattr(claim_module, "_insert_typed_claim", fake_insert)
    with pytest.raises(SessionError) as exc_info:
        claim_module.claim_work(conn, session_id="sess-B", **claim_kwargs)
    assert exc_info.value.code == "ALREADY_CLAIMED"
    assert "sess-A" in str(exc_info.value)


def _writer(
    db_path: str, session_id: str, target, barrier: threading.Barrier,
    errors: list[Exception], successes: list[str],
) -> None:
    conn = connect_test_db(db_path)
    try:
        barrier.wait(timeout=10.0)
        claim_module.claim_work(conn, session_id=session_id, target=target)
        successes.append(session_id)
    except Exception as exc:  # noqa: BLE001 - collected for assertion
        errors.append(exc)
    finally:
        conn.close()


@contextlib.contextmanager
def _bootstrap_db(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=lambda: _apply_on_backend(_create_schema)) as db_path:
        conn = connect_test_db(db_path)
        try:
            _register_pair(conn)
            conn.commit()
        finally:
            conn.close()
        yield db_path


@pytest.mark.parametrize(
    ("target", "where_sql", "params"),
    [
        (make_item_target(9999), "item_id=%s AND target_kind='item'", (9999,)),
        (
            make_epic_task_target(4242, 3),
            "epic_id=%s AND task_num=%s AND target_kind='epic_task'",
            (4242, 3),
        ),
    ],
)
def test_concurrent_claim_serializes(tmp_path, target, where_sql, params):
    with _bootstrap_db(tmp_path) as db_path:
        barrier = threading.Barrier(2)
        errors: list[Exception] = []
        successes: list[str] = []
        threads = [
            threading.Thread(
                target=_writer,
                args=(db_path, sid, target, barrier, errors, successes),
            )
            for sid in ("sess-A", "sess-B")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15.0)

        assert len(successes) == 1, f"successes={successes!r} errors={errors!r}"
        assert len(errors) == 1
        assert isinstance(errors[0], SessionError)
        assert errors[0].code == "ALREADY_CLAIMED"

        conn = connect_test_db(db_path)
        try:
            rows = conn.execute(
                "SELECT session_id FROM work_claims "
                f"WHERE {where_sql} AND released_at IS NULL",
                params,
            ).fetchall()
        finally:
            conn.close()
    assert [row["session_id"] for row in rows] == successes

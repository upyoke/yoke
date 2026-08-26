"""Concurrency proofs for work-claim acquire, release, and handoff."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from yoke_core.domain import (
    claim_chain_state,
    sessions,
    sessions_lifecycle_claim_release,
    sessions_render_reclaim,
)
from yoke_core.domain.sessions import SessionError, claim_work, handoff_claim
from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
from yoke_core.domain.work_claim_targets import decode_scope


_CONCURRENCY_TIMEOUT_SECONDS = 30


def _connections(test_db) -> tuple[Any, Any]:
    name = str(test_db.info.dbname)
    return connect_test_database(name), connect_test_database(name)


def _join(thread: threading.Thread) -> None:
    thread.join(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
    assert not thread.is_alive(), f"thread {thread.name} did not finish"


def test_cross_item_stale_cleanup_does_not_invert_target_locks(
    test_db,
    monkeypatch,
) -> None:
    item_ids = (9611, 9612)
    for item_id in item_ids:
        insert_item(test_db, id=item_id, workflow_id="issue")
    for session_id in ("stale-holder", "fresh-a", "fresh-b"):
        _register(test_db, session_id=session_id)
    for item_id in item_ids:
        claim_work(
            test_db,
            session_id="stale-holder",
            item_id=item_id,
        )
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    test_db.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id='stale-holder'",
        (stale_at,),
    )
    test_db.execute(
        "UPDATE work_claims SET claimed_at=%s,last_heartbeat=%s "
        "WHERE session_id='stale-holder'",
        (stale_at, stale_at),
    )
    test_db.commit()

    cleanup_barrier = threading.Barrier(2)
    original_cleanup = sessions.clean_stale_harness_sessions

    def synchronized_cleanup(conn: Any, *args: Any, **kwargs: Any) -> Any:
        cleanup_barrier.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        return original_cleanup(conn, *args, **kwargs)

    monkeypatch.setattr(
        sessions,
        "clean_stale_harness_sessions",
        synchronized_cleanup,
    )
    first_conn, second_conn = _connections(test_db)
    outcomes: dict[str, Any] = {}

    def acquire(name: str, conn: Any, item_id: int) -> None:
        try:
            outcomes[name] = claim_work(
                conn,
                session_id=name,
                item_id=item_id,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes[name] = exc

    workers = (
        threading.Thread(
            target=acquire,
            args=("fresh-a", first_conn, item_ids[0]),
            name="cross-item-acquire-a",
        ),
        threading.Thread(
            target=acquire,
            args=("fresh-b", second_conn, item_ids[1]),
            name="cross-item-acquire-b",
        ),
    )
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            _join(worker)
    finally:
        first_conn.close()
        second_conn.close()

    assert all(
        not isinstance(outcomes[name], BaseException) for name in ("fresh-a", "fresh-b")
    )
    holders = test_db.execute(
        "SELECT session_id,scope FROM work_claims "
        "WHERE released_at IS NULL AND target_kind='item' ORDER BY session_id",
    ).fetchall()
    assert [(row[0], int(decode_scope(row[1])["item_id"])) for row in holders] == [
        ("fresh-a", item_ids[0]),
        ("fresh-b", item_ids[1]),
    ]


def test_release_wins_before_handoff_fetch_without_resurrection(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9621
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id="source-session")
    _register(test_db, session_id="target-session")
    claim = claim_work(
        test_db,
        session_id="source-session",
        item_id=item_id,
    )
    release_conn, handoff_conn = _connections(test_db)
    release_locked = threading.Event()
    continue_release = threading.Event()
    handoff_started = threading.Event()
    handoff_done = threading.Event()
    outcomes: dict[str, Any] = {}
    original_session_lock = (
        sessions_lifecycle_claim_release.lock_session_rows_for_claim_lifecycle
    )

    def pause_after_session_lock(conn: Any, session_ids):
        rows = original_session_lock(conn, session_ids)
        release_locked.set()
        assert continue_release.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        return rows

    monkeypatch.setattr(
        sessions_lifecycle_claim_release,
        "lock_session_rows_for_claim_lifecycle",
        pause_after_session_lock,
    )

    def release() -> None:
        try:
            outcomes["release"] = release_claim_by_id(
                release_conn,
                int(claim["id"]),
                reason="release wins handoff race",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["release"] = exc

    def handoff() -> None:
        handoff_started.set()
        try:
            outcomes["handoff"] = handoff_claim(
                handoff_conn,
                int(claim["id"]),
                "target-session",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["handoff"] = exc
        finally:
            handoff_done.set()

    releaser = threading.Thread(target=release, name="claim-release-writer")
    handoff_worker = threading.Thread(target=handoff, name="release-handoff-race")
    try:
        releaser.start()
        assert release_locked.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        handoff_worker.start()
        assert handoff_started.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        assert not handoff_done.wait(timeout=0.2)
        continue_release.set()
        _join(releaser)
        _join(handoff_worker)
    finally:
        continue_release.set()
        release_conn.close()
        handoff_conn.close()

    assert not isinstance(outcomes["release"], BaseException)
    error = outcomes["handoff"]
    assert isinstance(error, SessionError)
    assert error.code == "ALREADY_RELEASED"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id='target-session' AND released_at IS NULL"
        ).fetchone()[0]
        == 0
    )


def test_claim_reason_failure_rolls_back_claim_and_session_focus(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9631
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id="claim-focus-session")

    def fail_reason(*_args, **_kwargs):
        raise RuntimeError("claim reason interrupted")

    monkeypatch.setattr(
        claim_chain_state,
        "record_claim_reason",
        fail_reason,
    )
    with pytest.raises(RuntimeError, match="claim reason interrupted"):
        claim_work(
            test_db,
            session_id="claim-focus-session",
            item_id=item_id,
        )

    row = test_db.execute(
        "SELECT current_item_id FROM harness_sessions "
        "WHERE session_id='claim-focus-session'",
    ).fetchone()
    claim_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id='claim-focus-session'",
    ).fetchone()[0]
    assert row[0] is None
    assert int(claim_count) == 0


def test_handoff_focus_failure_rolls_back_both_claim_sides(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9632
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id="handoff-source-session")
    _register(test_db, session_id="handoff-target-session")
    claim = claim_work(
        test_db,
        session_id="handoff-source-session",
        item_id=item_id,
    )

    def fail_target_focus(*_args, **_kwargs):
        raise RuntimeError("target focus interrupted")

    monkeypatch.setattr(
        sessions_render_reclaim,
        "set_current_item",
        fail_target_focus,
    )
    with pytest.raises(RuntimeError, match="target focus interrupted"):
        handoff_claim(
            test_db,
            int(claim["id"]),
            "handoff-target-session",
        )

    old_claim = test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s",
        (int(claim["id"]),),
    ).fetchone()
    target_claims = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id='handoff-target-session'",
    ).fetchone()[0]
    focus_rows = test_db.execute(
        "SELECT session_id, current_item_id FROM harness_sessions "
        "WHERE session_id IN ("
        "'handoff-source-session','handoff-target-session'"
        ") ORDER BY session_id",
    ).fetchall()
    assert old_claim[0] is None
    assert int(target_claims) == 0
    assert [(row[0], row[1]) for row in focus_rows] == [
        ("handoff-source-session", str(item_id)),
        ("handoff-target-session", None),
    ]

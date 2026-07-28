"""Concurrency and rollback proofs for session-scoped claim lifecycle writes."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from runtime.harness import harness_sessions_claims_acquire as runtime_claims
from yoke_core.domain import (
    sessions_lifecycle_reactivation,
    sessions_render_end,
    sessions_render_reclaim,
)
from yoke_core.domain.sessions import (
    SessionError,
    claim_work,
    end_session,
    handoff_claim,
    reclaim_stale_session,
)


def _connections(test_db, count: int = 2) -> tuple[Any, ...]:
    database_name = str(test_db.info.dbname)
    return tuple(connect_test_database(database_name) for _ in range(count))


def _join(worker: threading.Thread) -> None:
    worker.join(timeout=10)
    assert not worker.is_alive(), f"thread {worker.name} did not finish"


def _pause_after_end_session_lock(monkeypatch):
    locked = threading.Event()
    continue_end = threading.Event()
    original_lock = sessions_render_end.lock_session_rows_for_claim_lifecycle

    def pause(conn: Any, session_ids) -> dict[str, str | None]:
        rows = original_lock(conn, session_ids)
        locked.set()
        assert continue_end.wait(timeout=10)
        return rows

    monkeypatch.setattr(
        sessions_render_end,
        "lock_session_rows_for_claim_lifecycle",
        pause,
    )
    return locked, continue_end


@pytest.mark.parametrize("claim_surface", ("domain", "runtime"))
def test_end_wins_session_lock_before_claim_without_resurrection(
    test_db,
    monkeypatch,
    claim_surface: str,
) -> None:
    """Both claim surfaces re-check the active session after waiting."""
    item_id = 9711 if claim_surface == "domain" else 9712
    session_id = f"{claim_surface}-end-race"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=session_id)
    end_conn, claim_conn = _connections(test_db)
    end_locked, continue_end = _pause_after_end_session_lock(monkeypatch)
    claim_started = threading.Event()
    claim_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def finish_session() -> None:
        try:
            outcomes["end"] = end_session(end_conn, session_id)
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["end"] = exc

    def acquire() -> None:
        claim_started.set()
        try:
            if claim_surface == "domain":
                outcomes["claim"] = claim_work(
                    claim_conn,
                    session_id=session_id,
                    item_id=f"YOK-{item_id}",
                )
            else:
                outcomes["claim"] = runtime_claims.cmd_claim(
                    claim_conn,
                    session_id,
                    "item",
                    item_id=item_id,
                )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["claim"] = exc
        finally:
            claim_done.set()

    ending = threading.Thread(target=finish_session, name=f"{claim_surface}-end")
    claiming = threading.Thread(target=acquire, name=f"{claim_surface}-claim")
    try:
        ending.start()
        assert end_locked.wait(timeout=10)
        claiming.start()
        assert claim_started.wait(timeout=10)
        assert not claim_done.wait(timeout=0.2)
        continue_end.set()
        _join(ending)
        _join(claiming)
    finally:
        continue_end.set()
        end_conn.close()
        claim_conn.close()

    assert not isinstance(outcomes["end"], BaseException)
    if claim_surface == "domain":
        assert isinstance(outcomes["claim"], SessionError)
        assert outcomes["claim"].code == "SESSION_ENDED"
    else:
        assert isinstance(outcomes["claim"], PermissionError)
        assert "already ended" in str(outcomes["claim"])
    active_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (session_id,),
    ).fetchone()[0]
    assert int(active_count) == 0


def test_target_end_wins_before_handoff_without_target_claim(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9721
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id="handoff-source-active")
    _register(test_db, session_id="handoff-target-ending")
    claim = claim_work(
        test_db,
        session_id="handoff-source-active",
        item_id=f"YOK-{item_id}",
    )
    end_conn, handoff_conn = _connections(test_db)
    end_locked, continue_end = _pause_after_end_session_lock(monkeypatch)
    handoff_started = threading.Event()
    handoff_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def finish_target() -> None:
        outcomes["end"] = end_session(end_conn, "handoff-target-ending")

    def transfer() -> None:
        handoff_started.set()
        try:
            outcomes["handoff"] = handoff_claim(
                handoff_conn,
                int(claim["id"]),
                "handoff-target-ending",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["handoff"] = exc
        finally:
            handoff_done.set()

    ending = threading.Thread(target=finish_target, name="handoff-target-end")
    handing_off = threading.Thread(target=transfer, name="handoff-target-transfer")
    try:
        ending.start()
        assert end_locked.wait(timeout=10)
        handing_off.start()
        assert handoff_started.wait(timeout=10)
        assert not handoff_done.wait(timeout=0.2)
        continue_end.set()
        _join(ending)
        _join(handing_off)
    finally:
        continue_end.set()
        end_conn.close()
        handoff_conn.close()

    error = outcomes["handoff"]
    assert isinstance(error, SessionError)
    assert error.code == "SESSION_ENDED"
    source_claim = test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s",
        (int(claim["id"]),),
    ).fetchone()
    target_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims "
        "WHERE session_id='handoff-target-ending' AND released_at IS NULL",
    ).fetchone()[0]
    assert source_claim[0] is None
    assert int(target_count) == 0


def test_reclaim_wins_session_lock_before_claim_without_resurrection(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9731
    session_id = "reclaim-end-race"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=session_id)
    reclaim_conn, claim_conn = _connections(test_db)
    reclaim_locked = threading.Event()
    continue_reclaim = threading.Event()
    claim_done = threading.Event()
    outcomes: dict[str, Any] = {}
    original_lock = sessions_render_reclaim.lock_session_rows_for_claim_lifecycle

    def pause(conn: Any, session_ids) -> dict[str, str | None]:
        rows = original_lock(conn, session_ids)
        reclaim_locked.set()
        assert continue_reclaim.wait(timeout=10)
        return rows

    monkeypatch.setattr(
        sessions_render_reclaim,
        "lock_session_rows_for_claim_lifecycle",
        pause,
    )

    def reclaim() -> None:
        outcomes["reclaim"] = reclaim_stale_session(reclaim_conn, session_id)

    def acquire() -> None:
        try:
            outcomes["claim"] = claim_work(
                claim_conn,
                session_id=session_id,
                item_id=f"YOK-{item_id}",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["claim"] = exc
        finally:
            claim_done.set()

    reclaiming = threading.Thread(target=reclaim, name="session-reclaim")
    claiming = threading.Thread(target=acquire, name="claim-during-reclaim")
    try:
        reclaiming.start()
        assert reclaim_locked.wait(timeout=10)
        claiming.start()
        assert not claim_done.wait(timeout=0.2)
        continue_reclaim.set()
        _join(reclaiming)
        _join(claiming)
    finally:
        continue_reclaim.set()
        reclaim_conn.close()
        claim_conn.close()

    assert outcomes["reclaim"]["ended_at"] is not None
    assert isinstance(outcomes["claim"], SessionError)
    assert outcomes["claim"].code == "SESSION_ENDED"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id=%s AND released_at IS NULL",
            (session_id,),
        ).fetchone()[0]
        == 0
    )


def test_end_failure_rolls_back_claim_release_focus_and_terminal_row(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9741
    session_id = "end-release-rollback"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=session_id)
    claim = claim_work(
        test_db,
        session_id=session_id,
        item_id=f"YOK-{item_id}",
    )
    emitted_events: list[str] = []
    monkeypatch.setattr(
        sessions_render_end._sa,
        "_emit_session_event",
        lambda event_name, **_kwargs: emitted_events.append(event_name),
    )

    def fail_after_release(*_args, **_kwargs):
        raise RuntimeError("session end interrupted after staged release")

    monkeypatch.setattr(
        sessions_render_end,
        "sweep_orphaned_tool_calls",
        fail_after_release,
    )
    with pytest.raises(RuntimeError, match="interrupted after staged release"):
        end_session(test_db, session_id)

    session = test_db.execute(
        "SELECT ended_at,current_item_id FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    stored_claim = test_db.execute(
        "SELECT released_at,release_reason FROM work_claims WHERE id=%s",
        (int(claim["id"]),),
    ).fetchone()
    assert tuple(session) == (None, str(item_id))
    assert tuple(stored_claim) == (None, None)
    assert emitted_events == []


def test_resume_notice_failure_rolls_back_reacquired_claim_and_notice(
    test_db,
    monkeypatch,
) -> None:
    item_id = 9751
    session_id = "reactivation-notice-rollback"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=session_id)
    claim_work(
        test_db,
        session_id=session_id,
        item_id=f"YOK-{item_id}",
    )
    end_session(test_db, session_id)
    original_write = sessions_lifecycle_reactivation.write_pending_resume_notice

    def fail_after_notice(conn: Any, *args: Any, **kwargs: Any) -> bool:
        original_write(conn, *args, **kwargs)
        raise RuntimeError("resume notice interrupted")

    monkeypatch.setattr(
        sessions_lifecycle_reactivation,
        "write_pending_resume_notice",
        fail_after_notice,
    )
    _register(test_db, session_id=session_id)

    session = test_db.execute(
        "SELECT ended_at,pending_resume_notice FROM harness_sessions "
        "WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    active_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (session_id,),
    ).fetchone()[0]
    assert tuple(session) == (None, None)
    assert int(active_count) == 0

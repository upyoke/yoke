"""Concurrency proofs for session-first bulk and operator claim release."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from yoke_core.domain import (
    sessions_lifecycle_release_bulk,
    sessions_lifecycle_release_operator,
)
from yoke_core.domain.sessions import SessionError, claim_work, handoff_claim
from yoke_core.domain.sessions_lifecycle_release_bulk import release_all_claims
from yoke_core.domain.sessions_lifecycle_release_operator import (
    operator_override_release_claim,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)


def _connections(test_db) -> tuple[Any, Any]:
    database_name = str(test_db.info.dbname)
    return (
        connect_test_database(database_name),
        connect_test_database(database_name),
    )


def _join(worker: threading.Thread) -> None:
    worker.join(timeout=10)
    assert not worker.is_alive(), f"thread {worker.name} did not finish"


@pytest.mark.parametrize(
    "release_surface",
    ("bulk", "operator_by_id", "operator_by_item"),
)
def test_release_holds_source_session_before_handoff_parent_lock(
    test_db,
    monkeypatch,
    release_surface: str,
) -> None:
    """A release wins cleanly while handoff waits on the source session."""
    item_id = {
        "bulk": 9761,
        "operator_by_id": 9762,
        "operator_by_item": 9763,
    }[release_surface]
    source_session = f"{release_surface}-release-source"
    target_session = f"{release_surface}-release-target"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=source_session)
    _register(test_db, session_id=target_session)
    claim = claim_work(
        test_db,
        session_id=source_session,
        item_id=item_id,
    )
    release_conn, handoff_conn = _connections(test_db)
    release_locked = threading.Event()
    continue_release = threading.Event()
    handoff_started = threading.Event()
    handoff_done = threading.Event()
    outcomes: dict[str, Any] = {}
    release_module = (
        sessions_lifecycle_release_bulk
        if release_surface == "bulk"
        else sessions_lifecycle_release_operator
    )
    original_session_lock = release_module.lock_session_rows_for_claim_lifecycle

    def pause_after_session_lock(conn: Any, session_ids):
        rows = original_session_lock(conn, session_ids)
        release_locked.set()
        assert continue_release.wait(timeout=10)
        return rows

    monkeypatch.setattr(
        release_module,
        "lock_session_rows_for_claim_lifecycle",
        pause_after_session_lock,
    )

    def release() -> None:
        try:
            if release_surface == "bulk":
                outcomes["release"] = release_all_claims(
                    release_conn,
                    source_session,
                    reason="released",
                )
            elif release_surface == "operator_by_id":
                outcomes["release"] = operator_override_release_claim(
                    release_conn,
                    item_id,
                    "lock-order regression",
                    claim_id=int(claim["id"]),
                )
            else:
                outcomes["release"] = operator_override_release_claim(
                    release_conn,
                    item_id,
                    "lock-order regression",
                )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["release"] = exc

    def handoff() -> None:
        handoff_started.set()
        try:
            outcomes["handoff"] = handoff_claim(
                handoff_conn,
                int(claim["id"]),
                target_session,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["handoff"] = exc
        finally:
            handoff_done.set()

    releaser = threading.Thread(
        target=release,
        name=f"{release_surface}-release-writer",
    )
    handing_off = threading.Thread(
        target=handoff,
        name=f"{release_surface}-handoff-writer",
    )
    try:
        releaser.start()
        assert release_locked.wait(timeout=10)
        handing_off.start()
        assert handoff_started.wait(timeout=10)
        assert not handoff_done.wait(timeout=0.2)
        continue_release.set()
        _join(releaser)
        _join(handing_off)
    finally:
        continue_release.set()
        release_conn.close()
        handoff_conn.close()

    assert not isinstance(outcomes["release"], BaseException)
    error = outcomes["handoff"]
    assert isinstance(error, SessionError)
    assert error.code == "ALREADY_RELEASED"
    target_claim_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (target_session,),
    ).fetchone()[0]
    source_focus = test_db.execute(
        "SELECT current_item_id FROM harness_sessions WHERE session_id=%s",
        (source_session,),
    ).fetchone()[0]
    assert int(target_claim_count) == 0
    assert source_focus is None


def test_handoff_revalidates_target_after_terminal_transition_parent_lock(
    test_db,
) -> None:
    """A waiting handoff cannot resurrect a claim after item termination."""
    item_id = 9771
    source_session = "terminal-handoff-source"
    target_session = "terminal-handoff-target"
    insert_item(test_db, id=item_id, workflow_id="issue")
    _register(test_db, session_id=source_session)
    _register(test_db, session_id=target_session)
    claim = claim_work(
        test_db,
        session_id=source_session,
        item_id=item_id,
    )
    transition_conn, handoff_conn = _connections(test_db)
    handoff_started = threading.Event()
    handoff_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def transfer() -> None:
        handoff_started.set()
        try:
            outcomes["handoff"] = handoff_claim(
                handoff_conn,
                int(claim["id"]),
                target_session,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["handoff"] = exc
        finally:
            handoff_done.set()

    handing_off = threading.Thread(
        target=transfer,
        name="terminal-transition-handoff",
    )
    try:
        lock_item_workflow_bindings(transition_conn, (item_id,))
        handing_off.start()
        assert handoff_started.wait(timeout=10)
        assert not handoff_done.wait(timeout=0.2)
        transition_conn.execute(
            "UPDATE items SET status='done' WHERE id=%s",
            (item_id,),
        )
        transition_conn.commit()
        _join(handing_off)
    finally:
        transition_conn.rollback()
        transition_conn.close()
        handoff_conn.close()

    error = outcomes["handoff"]
    assert isinstance(error, SessionError)
    assert error.code == "INVALID_CLAIM"
    assert "terminal" in str(error)
    source_claim = test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s",
        (int(claim["id"]),),
    ).fetchone()
    target_count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (target_session,),
    ).fetchone()[0]
    assert source_claim[0] is None
    assert int(target_count) == 0

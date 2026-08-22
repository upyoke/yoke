"""Post-commit focus cleanup proofs for terminal item claim release."""

from __future__ import annotations

import threading
from typing import Any

from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from yoke_core.domain.sessions import set_current_item
from yoke_core.domain.sessions_claim_lifecycle_lock import (
    lock_session_rows_for_claim_lifecycle,
)
from yoke_core.domain.sessions_terminal_focus_cleanup import (
    clear_terminal_item_focuses,
)


def _connection(test_db):
    return connect_test_database(str(test_db.info.dbname))


def _join(worker: threading.Thread) -> None:
    worker.join(timeout=10)
    assert not worker.is_alive(), f"thread {worker.name} did not finish"


def test_terminal_focus_cleanup_is_sorted_and_moves_matching_focus_to_recent(
    test_db,
) -> None:
    for session_id in ("terminal-focus-b", "terminal-focus-a"):
        _register(test_db, session_id=session_id)
        set_current_item(test_db, session_id, 9811)

    cleared = clear_terminal_item_focuses(
        test_db,
        9811,
        ("terminal-focus-b", "terminal-focus-a", "terminal-focus-b"),
    )

    assert cleared == ("terminal-focus-a", "terminal-focus-b")
    rows = test_db.execute(
        "SELECT session_id,current_item_id,recent_item_id "
        "FROM harness_sessions WHERE session_id LIKE 'terminal-focus-%' "
        "ORDER BY session_id",
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("terminal-focus-a", None, "9811"),
        ("terminal-focus-b", None, "9811"),
    ]


def test_terminal_focus_cleanup_preserves_concurrent_new_focus(test_db) -> None:
    """A newer focus wins while cleanup waits for the session-row lock."""
    session_id = "terminal-focus-race"
    _register(test_db, session_id=session_id)
    set_current_item(test_db, session_id, 9821)
    focus_conn = _connection(test_db)
    cleanup_conn = _connection(test_db)
    cleanup_started = threading.Event()
    cleanup_done = threading.Event()
    outcomes: dict[str, Any] = {}

    lock_session_rows_for_claim_lifecycle(focus_conn, (session_id,))
    set_current_item(
        focus_conn,
        session_id,
        9822,
        commit=False,
    )

    def cleanup() -> None:
        cleanup_started.set()
        try:
            outcomes["cleared"] = clear_terminal_item_focuses(
                cleanup_conn,
                9821,
                (session_id,),
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["cleared"] = exc
        finally:
            cleanup_done.set()

    worker = threading.Thread(target=cleanup, name="terminal-focus-cleanup")
    try:
        worker.start()
        assert cleanup_started.wait(timeout=10)
        assert not cleanup_done.wait(timeout=0.2)
        focus_conn.commit()
        _join(worker)
    finally:
        focus_conn.rollback()
        focus_conn.close()
        cleanup_conn.close()

    assert outcomes["cleared"] == ()
    row = test_db.execute(
        "SELECT current_item_id,recent_item_id "
        "FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    ).fetchone()
    assert tuple(row) == ("9822", "9821")

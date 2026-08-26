# ruff: noqa: F811
"""Session focus falls back to another live item claim on release.

When the claim behind ``harness_sessions.current_item_id`` is released,
the session keeps pointing at the most recently claimed still-active
item rather than dropping to none. Covers the typed execution release,
the by-claim-id path, operator override, and terminal-item cleanup.
"""

from __future__ import annotations

from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain.sessions import (
    claim_work,
    clear_terminal_item_focuses,
    operator_override_release_claim,
    release_claim,
    release_item_claim_for_execution,
    set_current_item,
)
from yoke_core.domain.work_claim_targets import make_item_target


def _focus(conn, session_id: str) -> tuple[object, object]:
    row = conn.execute(
        "SELECT current_item_id, recent_item_id "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    current = row["current_item_id"]
    recent = row["recent_item_id"]
    return (
        None if current is None else str(current),
        None if recent is None else str(recent),
    )


def _claim_pair(conn, session_id: str = "sess-1"):
    _insert_claimable_items(conn, 1, 2)
    _register(conn, session_id=session_id)
    first = claim_work(conn, session_id=session_id, item_id=1)
    second = claim_work(conn, session_id=session_id, item_id=2)
    assert _focus(conn, session_id)[0] == "2"
    return first, second


def test_execution_release_falls_back_to_newest_remaining_item(conn):
    _claim_pair(conn)
    result = release_item_claim_for_execution(
        conn,
        "sess-1",
        2,
        "finalize-exit",
    )
    assert result["released"] is True
    current, recent = _focus(conn, "sess-1")
    assert current == "1"
    assert recent == "2"


def test_execution_release_clears_focus_when_no_item_claim_remains(conn):
    _insert_claimable_items(conn, 1)
    _register(conn)
    claim_work(conn, session_id="sess-1", item_id=1)
    release_item_claim_for_execution(conn, "sess-1", 1, "finalize-exit")
    current, recent = _focus(conn, "sess-1")
    assert current is None
    assert recent == "1"


def test_by_id_release_falls_back_to_remaining_item(conn):
    first, second = _claim_pair(conn)
    release_claim(conn, second["id"], reason="released")
    current, recent = _focus(conn, "sess-1")
    assert current == "1"
    assert recent == "2"
    assert first["id"] != second["id"]


def test_operator_override_of_focused_claim_falls_back(conn):
    _claim_pair(conn)
    operator_override_release_claim(conn, 2, "stranded after crash")
    current, recent = _focus(conn, "sess-1")
    assert current == "1"
    assert recent == "2"


def test_terminal_cleanup_falls_back_to_remaining_item_claim(conn):
    _claim_pair(conn)
    set_current_item(conn, "sess-1", 1)
    target = make_item_target(1)
    conn.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'completed' "
        "WHERE session_id = 'sess-1' AND target_kind = %s AND scope = %s "
        "AND released_at IS NULL",
        ("2026-08-22T00:00:00Z", target.kind, target.scope_json()),
    )
    conn.commit()
    cleared = clear_terminal_item_focuses(conn, 1, ("sess-1",))
    assert cleared == ("sess-1",)
    current, recent = _focus(conn, "sess-1")
    assert current == "2"
    assert recent == "1"

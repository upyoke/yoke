# ruff: noqa: F811
"""The work claim is the only writer of ``current_item_id``.

A session's focus slot answers "which item is this session working?",
so only claim acquisition puts an item there and only claim release
takes it away. Touching an item — filing it, moving its status — is
attribution, and records ``recent_item_id`` instead. These are the
cases observed live on a steering seat that filed items it never
claimed and read as working them.
"""

from __future__ import annotations

from runtime.api.test_sessions import (
    _insert_claimable_items,
    _register,
    conn,  # noqa: F401
)
from yoke_core.domain import steering_claims
from yoke_core.domain.backlog_session_attribution import record_touched_item
from yoke_core.domain.sessions import (
    claim_work,
    release_claim,
    release_claims_for_done_item,
)


def _focus(conn, session_id: str = "sess-1") -> tuple[object, object]:
    row = conn.execute(
        "SELECT current_item_id, recent_item_id "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    current, recent = row["current_item_id"], row["recent_item_id"]
    return (
        None if current is None else str(current),
        None if recent is None else str(recent),
    )


def test_filing_without_a_claim_leaves_the_focus_slot_empty(conn):
    _insert_claimable_items(conn, 1)
    _register(conn)

    record_touched_item(conn, 1, "sess-1")

    assert _focus(conn) == (None, "1")


def test_filing_from_a_steering_seat_leaves_the_focus_slot_empty(conn):
    """A steering claim is not an item claim, and never becomes one."""
    _insert_claimable_items(conn, 1)
    _register(conn)
    steering_claims.acquire(conn, session_id="sess-1", project_id=1)

    record_touched_item(conn, 1, "sess-1")

    assert _focus(conn) == (None, "1")


def test_filing_while_claimed_keeps_focus_on_the_claimed_item(conn):
    _insert_claimable_items(conn, 1, 2)
    _register(conn)
    claim_work(conn, session_id="sess-1", item_id=1)

    record_touched_item(conn, 2, "sess-1")

    assert _focus(conn) == ("1", "2")


def test_claim_then_release_leaves_the_focus_slot_empty(conn):
    _insert_claimable_items(conn, 1)
    _register(conn)
    claim = claim_work(conn, session_id="sess-1", item_id=1)
    assert _focus(conn) == ("1", None)

    release_claim(conn, claim["id"], reason="released")

    assert _focus(conn) == (None, "1")


def test_done_item_cleanup_releases_a_foreign_holder_focus(conn):
    """An item that finished is nobody's current work, holder included."""
    _insert_claimable_items(conn, 1)
    _register(conn, session_id="holder-1")
    claim_work(conn, session_id="holder-1", item_id=1)
    assert _focus(conn, "holder-1") == ("1", None)

    assert release_claims_for_done_item(conn, "1") == 1

    assert _focus(conn, "holder-1") == (None, "1")

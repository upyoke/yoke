"""``sessions.list`` names who actually holds a session's focused item.

A session's ``current_item`` is set by filing or updating the item as well
as by claiming it, so the roster carries the live holder separately. Cards
read it to keep an item another session is doing out of this one's work
position.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import (
    insert_item_claim,
    insert_session,
    iso,
)
from yoke_core.domain.sessions_list_read import list_sessions


def _row(session_id: str) -> dict:
    return next(
        row for row in list_sessions() if row["session_id"] == session_id
    )


def test_holder_names_the_live_session_claiming_the_focused_item(test_db):
    insert_session(test_db, "s-filer", current_item_id="70")
    insert_session(test_db, "s-worker", current_item_id="70")
    insert_item(test_db, id=70, title="filed here, claimed there")
    test_db.commit()
    insert_item_claim(test_db, "s-worker", 70)

    assert _row("s-filer")["current_item_holder_session_id"] == "s-worker"
    # The holder is somebody else's identity, so the session doing the work
    # reports none of its own.
    worker = _row("s-worker")
    assert worker["current_item_holder_session_id"] is None
    assert worker["owns_current_item"] is True


def test_unclaimed_focused_item_reports_no_holder(test_db):
    insert_session(test_db, "s-filer", current_item_id="71")
    insert_item(test_db, id=71, title="filed and untouched")
    test_db.commit()

    row = _row("s-filer")
    assert row["current_item_holder_session_id"] is None
    assert row["owns_current_item"] is False


def test_a_claim_left_by_an_ended_session_holds_nothing(test_db):
    insert_session(test_db, "s-filer", current_item_id="72")
    insert_session(test_db, "s-gone", current_item_id="72", ended_at=iso(30))
    insert_item(test_db, id=72, title="claimed by a session that is gone")
    test_db.commit()
    insert_item_claim(test_db, "s-gone", 72)

    assert _row("s-filer")["current_item_holder_session_id"] is None


def test_a_released_claim_stops_naming_its_holder(test_db):
    insert_session(test_db, "s-filer", current_item_id="73")
    insert_session(test_db, "s-worker", current_item_id="73")
    insert_item(test_db, id=73, title="claimed then released")
    test_db.commit()
    insert_item_claim(test_db, "s-worker", 73, released_at=iso(5))

    assert _row("s-filer")["current_item_holder_session_id"] is None

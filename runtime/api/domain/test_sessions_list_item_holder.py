"""``sessions.list`` names who actually holds a session's focused item.

A session's ``current_item`` is set by filing or updating the item as well
as by claiming it, so the roster carries the live holder separately. Cards
read it to keep an item another session is doing out of this one's work
position.

Three surfaces of one row answer "who holds this item" — the ``claims``
array, the ``holdings.current`` entries, and the ``owns_current_item`` /
``current_item_held_by_other_session_id`` pair — and a consumer reads
whichever it happens to reach. The last test here holds them to one
answer, because a reader that takes the held-by-other field for "the
holder" reads a holder's own row as unheld and concludes the item is
free.
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

    assert _row("s-filer")["current_item_held_by_other_session_id"] == "s-worker"
    # The holder is somebody else's identity, so the session doing the work
    # reports none of its own.
    worker = _row("s-worker")
    assert worker["current_item_held_by_other_session_id"] is None
    assert worker["owns_current_item"] is True


def test_unclaimed_focused_item_reports_no_holder(test_db):
    insert_session(test_db, "s-filer", current_item_id="71")
    insert_item(test_db, id=71, title="filed and untouched")
    test_db.commit()

    row = _row("s-filer")
    assert row["current_item_held_by_other_session_id"] is None
    assert row["owns_current_item"] is False


def test_a_claim_left_by_an_ended_session_holds_nothing(test_db):
    insert_session(test_db, "s-filer", current_item_id="72")
    insert_session(test_db, "s-gone", current_item_id="72", ended_at=iso(30))
    insert_item(test_db, id=72, title="claimed by a session that is gone")
    test_db.commit()
    insert_item_claim(test_db, "s-gone", 72)

    assert _row("s-filer")["current_item_held_by_other_session_id"] is None


def test_a_released_claim_stops_naming_its_holder(test_db):
    insert_session(test_db, "s-filer", current_item_id="73")
    insert_session(test_db, "s-worker", current_item_id="73")
    insert_item(test_db, id=73, title="claimed then released")
    test_db.commit()
    insert_item_claim(test_db, "s-worker", 73, released_at=iso(5))

    assert _row("s-filer")["current_item_held_by_other_session_id"] is None


def _holder_per_item(rows: list[dict]) -> tuple[dict, dict, dict]:
    """Read "who holds each focused item" once per available surface.

    Returns one item-to-session mapping per surface, in the order
    ``claims`` array, ``holdings.current``, attribution-field pair. Every
    focused item appears in all three, mapped to ``None`` where that
    surface names no holder, so a surface staying silent is a visible
    disagreement rather than a missing key.
    """
    by_claims: dict = {}
    by_holdings: dict = {}
    by_fields: dict = {}
    focused = [row for row in rows if row["current_item"]]
    for row in focused:
        for reading in (by_claims, by_holdings, by_fields):
            reading.setdefault(row["current_item"], None)
    for row in focused:
        item = row["current_item"]
        if any(
            claim.get("target_kind") == "item" and claim.get("target") == item
            for claim in row["claims"]
        ):
            by_claims[item] = row["session_id"]
        if any(
            held.get("holding_kind") == "work_claim"
            and held.get("target_kind") == "item"
            and held.get("target") == item
            for held in row["holdings"]["current"]
        ):
            by_holdings[item] = row["session_id"]
        named = (
            row["session_id"]
            if row["owns_current_item"]
            else row["current_item_held_by_other_session_id"]
        )
        if named:
            by_fields[item] = named
    return by_claims, by_holdings, by_fields


def test_every_surface_of_the_roster_names_the_same_holder(test_db):
    """One holder per item, whichever field a consumer happens to read."""
    # Held, and focused by its holder and by the session that filed it.
    insert_session(test_db, "s-filer", current_item_id="80")
    insert_session(test_db, "s-worker", current_item_id="80")
    # Filed and never picked up.
    insert_session(test_db, "s-idle", current_item_id="81")
    # Claimed, then released.
    insert_session(test_db, "s-done", current_item_id="82")
    insert_item(test_db, id=80, title="held right now")
    insert_item(test_db, id=81, title="filed and untouched")
    insert_item(test_db, id=82, title="worked and handed back")
    test_db.commit()
    insert_item_claim(test_db, "s-worker", 80)
    insert_item_claim(test_db, "s-done", 82, released_at=iso(5))

    by_claims, by_holdings, by_fields = _holder_per_item(list_sessions())

    assert by_claims == by_holdings == by_fields
    assert by_fields == {"YOK-80": "s-worker", "YOK-81": None, "YOK-82": None}

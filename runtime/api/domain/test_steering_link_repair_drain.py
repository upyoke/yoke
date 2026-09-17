"""A sanctioned link repair reseats unacked role mail without reacquire."""

from __future__ import annotations

from yoke_core.domain import steering_message_drain
from yoke_core.domain.session_message_receipts import (
    acknowledge_message,
    cancel_message,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.steering_message_recipients import (
    STATE_ACKNOWLEDGED,
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


BODY = "Blocked: the merge gate went red on the schema converge step."
AREA = "AREA-PLAN"
OTHER = "OTHER-PLAN"
ITEM_ID = 101
AREA_SCOPE = '{"document":"AREA-PLAN","project_id":1}'
OTHER_SCOPE = '{"document":"OTHER-PLAN","project_id":1}'


def _seat(conn, *, claim_id: int, session_id: str, scope: str) -> None:
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'steering',?,?)",
        (claim_id, session_id, scope, NOW_TEXT),
    )
    conn.commit()


def _area_other_seats(conn) -> None:
    _seat(conn, claim_id=11, session_id="s3", scope=AREA_SCOPE)
    _seat(conn, claim_id=12, session_id="s4", scope=OTHER_SCOPE)


def _say(conn, **selector_values):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(steering=True, **selector_values),
        body=BODY,
        now=NOW,
    )


def _link(conn, slug: str) -> None:
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) VALUES (?,1,?,?) "
        "ON CONFLICT(item_id) DO UPDATE SET strategy_doc_slug=excluded.strategy_doc_slug",
        (ITEM_ID, slug, NOW_TEXT),
    )
    conn.commit()


def _reseat(conn):
    result = steering_message_drain.reseat_item_messages(conn, item_id=ITEM_ID, now=NOW)
    conn.commit()
    return result


def _row(conn, message_id: str) -> dict:
    found = conn.execute(
        "SELECT * FROM actor_message_recipients WHERE message_id=?", (message_id,)
    ).fetchone()
    return dict(found)


def _session_row(conn, message_id: str, session_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM session_message_recipients "
        "WHERE message_id=? AND session_id=?",
        (message_id, session_id),
    ).fetchone()
    return dict(row) if row else None


def test_repaired_link_delivers_parked_mail_to_the_already_live_seat() -> None:
    conn = message_connection()
    _seat(conn, claim_id=11, session_id="s3", scope=AREA_SCOPE)
    sent = _say(conn)
    assert _row(conn, sent["message_id"])["state"] == STATE_AWAITING_SEAT

    _link(conn, AREA)
    handoff = _reseat(conn)

    row = _row(conn, sent["message_id"])
    assert handoff["drained_count"] == 1
    assert row["state"] == STATE_DELIVERED
    assert row["seat_session_id"] == "s3"
    assert row["seat_claim_id"] == 11


def test_changed_document_moves_unacked_mail_to_the_new_covering_seat() -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn)
    assert _row(conn, sent["message_id"])["seat_session_id"] == "s3"

    _link(conn, OTHER)
    _reseat(conn)

    row = _row(conn, sent["message_id"])
    assert row["state"] == STATE_DELIVERED
    assert row["seat_session_id"] == "s4"
    assert row["seat_claim_id"] == 12


def test_already_acknowledged_mail_stays_with_its_seat() -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn)
    acknowledge_message(conn, message_id=sent["message_id"], session_id="s3", now=NOW)

    _link(conn, OTHER)
    handoff = _reseat(conn)

    row = _row(conn, sent["message_id"])
    assert handoff["drained_count"] == 0
    assert row["state"] == STATE_ACKNOWLEDGED
    assert row["seat_session_id"] == "s3"


def test_no_live_seat_parks_mail_after_the_link_changes() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2", scope='{"project_id":1}')
    sent = _say(conn)
    assert _row(conn, sent["message_id"])["seat_session_id"] == "s2"

    _link(conn, AREA)
    handoff = _reseat(conn)

    row = _row(conn, sent["message_id"])
    assert handoff["parked_count"] == 1
    assert row["state"] == STATE_AWAITING_SEAT
    assert row["seat_session_id"] is None


def test_ended_session_is_not_a_covering_seat() -> None:
    conn = message_connection()
    _seat(conn, claim_id=11, session_id="s3", scope=AREA_SCOPE)
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, "s3"),
    )
    conn.commit()
    sent = _say(conn)
    assert _row(conn, sent["message_id"])["state"] == STATE_AWAITING_SEAT

    _link(conn, AREA)
    _reseat(conn)

    assert _row(conn, sent["message_id"])["state"] == STATE_AWAITING_SEAT
    assert _row(conn, sent["message_id"])["seat_session_id"] is None


def test_concurrent_acknowledgement_is_not_undone(monkeypatch) -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn)
    original = steering_message_drain._item_unacked_rows

    def racing_read(db, item_id):
        rows = original(db, item_id)
        acknowledge_message(db, message_id=sent["message_id"], session_id="s3", now=NOW)
        return rows

    monkeypatch.setattr(steering_message_drain, "_item_unacked_rows", racing_read)
    _link(conn, OTHER)
    handoff = _reseat(conn)

    row = _row(conn, sent["message_id"])
    assert handoff["drained_count"] == 0
    assert row["state"] == STATE_ACKNOWLEDGED
    assert row["acknowledged_at"] is not None
    assert row["seat_session_id"] == "s3"


def test_parked_mail_is_deliverable_when_the_same_seat_covers_again() -> None:
    conn = message_connection()
    _seat(conn, claim_id=11, session_id="s3", scope=AREA_SCOPE)
    _link(conn, AREA)
    sent = _say(conn)
    assert _session_row(conn, sent["message_id"], "s3")["state"] == "pending"

    _link(conn, OTHER)
    _reseat(conn)
    assert _session_row(conn, sent["message_id"], "s3")["state"] == "cancelled"
    assert _row(conn, sent["message_id"])["state"] == STATE_AWAITING_SEAT

    _link(conn, AREA)
    _reseat(conn)
    revived = _session_row(conn, sent["message_id"], "s3")
    assert revived["state"] == "pending"
    assert revived["cancelled_at"] is None
    role = _row(conn, sent["message_id"])
    assert role["state"] == STATE_DELIVERED
    assert role["seat_session_id"] == "s3"


def test_existing_destination_recipient_is_kept_without_duplicate_keys() -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn, session_ids=["s4"])
    assert _session_row(conn, sent["message_id"], "s4")["state"] == "pending"

    _link(conn, OTHER)
    _reseat(conn)

    dest = _session_row(conn, sent["message_id"], "s4")
    source = _session_row(conn, sent["message_id"], "s3")
    counts = conn.execute(
        "SELECT session_id, COUNT(*) FROM session_message_recipients "
        "WHERE message_id=? GROUP BY session_id",
        (sent["message_id"],),
    ).fetchall()
    assert dest["state"] == "pending"
    assert source["state"] == "cancelled"
    assert all(int(row[1]) == 1 for row in counts)
    assert _row(conn, sent["message_id"])["seat_session_id"] == "s4"


def test_existing_destination_acknowledgement_is_preserved() -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn, session_ids=["s4"])
    acknowledge_message(conn, message_id=sent["message_id"], session_id="s4", now=NOW)

    _link(conn, OTHER)
    _reseat(conn)

    dest = _session_row(conn, sent["message_id"], "s4")
    assert dest["state"] == "acknowledged"
    assert dest["acknowledged_at"] is not None
    role = _row(conn, sent["message_id"])
    assert role["state"] == STATE_DELIVERED
    assert role["seat_session_id"] == "s4"


def test_cancelled_message_is_not_resurrected_by_reseat() -> None:
    conn = message_connection()
    _area_other_seats(conn)
    _link(conn, AREA)
    sent = _say(conn)
    cancel_message(conn, message_id=sent["message_id"], actor_id=10, now=NOW)

    _link(conn, OTHER)
    _reseat(conn)

    message = dict(
        conn.execute(
            "SELECT cancelled_at FROM session_messages WHERE message_id=?",
            (sent["message_id"],),
        ).fetchone()
    )
    assert message["cancelled_at"] is not None
    role = _row(conn, sent["message_id"])
    assert role["seat_session_id"] == "s3"

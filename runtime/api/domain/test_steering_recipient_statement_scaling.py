"""Settled steering history must not grow the drain/count read.

The report's awaiting-seat count used to load every role-addressed row
in the project, including acknowledged and cancelled mail, then resolve
document membership per row. This file plants thousands of those settled
rows beside a few actionable ones and checks two properties: the scoped
count and drainable ids stay the same, and the number of statements does
not grow with the settled pile.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    PROJECT_SCOPE,
    _end,
    _link_document,
    _say_steering,
    _seat,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.steering_message_drain import drain_to_seat
from yoke_core.domain.steering_message_recipients import (
    awaiting_seat_count,
    drainable_rows,
)


SMALL_HISTORY = 2_000
LARGE_HISTORY = 4_000
SCOPE_AREA = {"project_id": 1, "document": "AREA-PLAN"}
SCOPE_PLAN = {"project_id": 1, "document": "CURRENT-PLAN"}


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def _insert_acknowledged(conn, count: int, *, project_id: int = 1) -> None:
    """Finished reports a later count must not re-inspect one-by-one."""
    messages = []
    recipients = []
    for index in range(count):
        message_id = f"settled-{project_id}-{index:05d}"
        body = f"DONE ALP-1 close-out reporting landed ({index})."
        stamp = NOW_TEXT
        messages.append(
            (
                message_id,
                10,
                "s1",
                body,
                _sha(body),
                '{"steering":true}',
                stamp,
                stamp,
            )
        )
        recipients.append(
            (
                message_id,
                "steering",
                "acknowledged",
                stamp,
                '{"project_id":1}' if project_id == 1 else '{"project_id":2}',
                101 if project_id == 1 else 201,
                project_id,
                "s2",
                stamp,
                stamp,
            )
        )
    conn.executemany(
        "INSERT INTO session_messages (message_id, sender_actor_id, "
        "sender_session_id, body, body_sha256, selector_snapshot, "
        "created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
        messages,
    )
    conn.executemany(
        "INSERT INTO actor_message_recipients (message_id, recipient_kind, "
        "state, created_at, steering_scope, sender_item_id, project_id, "
        "seat_session_id, delivered_at, acknowledged_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        recipients,
    )
    conn.commit()


def _drainable_ids(conn, *, scope=PROJECT_SCOPE, project_id: int = 1) -> list[str]:
    return [
        str(row["message_id"])
        for row in drainable_rows(conn, scope=scope, project_id=project_id)
    ]


def _count_sql(counting: CountingConnection, fragment: str) -> int:
    needle = fragment.lower()
    return sum(
        n for sql, n in counting.statements.items() if needle in sql.lower()
    )


def _measure(conn, *, scope=PROJECT_SCOPE, project_id: int = 1) -> dict[str, int]:
    counting = CountingConnection(conn)
    count = awaiting_seat_count(counting, project_id=project_id, scope=scope)
    return {
        "count": count,
        "statements": counting.count,
        "bodies": _count_sql(counting, " as body"),
        "links": _count_sql(counting, "item_strategy_docs"),
        "table_exists": _count_sql(counting, "sqlite_master"),
    }


def test_settled_history_does_not_change_drainable_ids_or_grow_reads() -> None:
    small = message_connection()
    large = message_connection()
    _insert_acknowledged(small, SMALL_HISTORY)
    _insert_acknowledged(large, LARGE_HISTORY)
    parked_small = _say_steering(small, body="Blocked: parked beside settled mail.")
    parked_large = _say_steering(large, body="Blocked: parked beside settled mail.")

    small_read = _measure(small)
    large_read = _measure(large)

    assert small_read["count"] == large_read["count"] == 1
    assert _drainable_ids(small) == [parked_small["message_id"]]
    assert _drainable_ids(large) == [parked_large["message_id"]]
    assert small_read["statements"] == large_read["statements"]
    assert small_read["bodies"] == large_read["bodies"] == 0
    assert small_read["links"] == large_read["links"] == 1
    assert small_read["table_exists"] == large_read["table_exists"] == 1


def test_the_count_path_does_not_fetch_bodies_the_drain_path_still_does() -> None:
    conn = message_connection()
    _insert_acknowledged(conn, SMALL_HISTORY)
    sent = _say_steering(conn, body="Blocked: need a seat for this one.")

    counted = CountingConnection(conn)
    assert awaiting_seat_count(counted, project_id=1, scope=PROJECT_SCOPE) == 1
    assert _count_sql(counted, " as body") == 0

    drained = CountingConnection(conn)
    rows = drainable_rows(drained, scope=PROJECT_SCOPE, project_id=1)
    assert [row["body"] for row in rows] == ["Blocked: need a seat for this one."]
    assert [row["message_id"] for row in rows] == [sent["message_id"]]
    assert _count_sql(drained, " as body") == 0
    assert _count_sql(drained, "select message_id, body") == 1


def test_cancelled_live_held_and_answered_rows_stay_out_of_the_count() -> None:
    conn = message_connection()
    _insert_acknowledged(conn, 50)
    cancelled = _say_steering(conn, body="Blocked: this ask was withdrawn.")
    conn.execute(
        "UPDATE session_messages SET cancelled_at=? WHERE message_id=?",
        (NOW_TEXT, cancelled["message_id"]),
    )
    conn.commit()
    _seat(conn, claim_id=10, session_id="s2")
    live = _say_steering(conn, body="Blocked: a live seat is holding this.")
    assert live["message_id"] not in _drainable_ids(conn)

    answered = _say_steering(
        conn, body="Should we take the schema converge fix?"
    )
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Take the schema converge fix and rerun the gate.",
        now=NOW + timedelta(minutes=1),
    )
    acknowledged = _say_steering(conn, body="Blocked: already acted on.")
    acknowledge_message(
        conn, message_id=acknowledged["message_id"], session_id="s2", now=NOW
    )
    stranded = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(steering=True),
        body="Blocked: the seat that took this then ended.",
        now=NOW + timedelta(minutes=2),
    )
    _end(conn, "s2")
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=10", (NOW_TEXT,))
    conn.commit()
    parked = _say_steering(conn, body="Blocked: nobody is steering now.")

    ids = set(_drainable_ids(conn))
    assert ids == {parked["message_id"], stranded["message_id"]}
    assert cancelled["message_id"] not in ids
    assert live["message_id"] not in ids
    assert answered["message_id"] not in ids
    assert acknowledged["message_id"] not in ids
    assert awaiting_seat_count(conn, project_id=1, scope=PROJECT_SCOPE) == 2


def test_item_linked_unlinked_and_cross_project_scopes_stay_distinct() -> None:
    conn = message_connection()
    _insert_acknowledged(conn, 80)
    _insert_acknowledged(conn, 40, project_id=2)
    unlinked = _say_steering(conn, body="Blocked: still on the project seat.")
    _link_document(conn, 101, "AREA-PLAN")
    linked = _say_steering(conn, body="Blocked: now this document's seat.")
    other = send_message(
        conn,
        actor_id=10,
        sender_session_id="s3",
        selector=selector(steering=True, steering_scope={"project_id": 2}),
        body="Blocked: beta has no seat.",
        now=NOW,
    )

    assert awaiting_seat_count(conn, project_id=1, scope=PROJECT_SCOPE) == 0
    assert awaiting_seat_count(conn, project_id=1, scope=SCOPE_AREA) == 2
    assert awaiting_seat_count(conn, project_id=1, scope=SCOPE_PLAN) == 0
    assert awaiting_seat_count(conn, project_id=2, scope={"project_id": 2}) == 1
    area_ids = set(_drainable_ids(conn, scope=SCOPE_AREA))
    assert {unlinked["message_id"], linked["message_id"]} <= area_ids
    assert other["message_id"] not in area_ids
    assert _drainable_ids(conn, scope={"project_id": 2}, project_id=2) == [
        other["message_id"]
    ]


def test_a_later_link_moves_parked_mail_without_rereading_settled_rows() -> None:
    conn = message_connection()
    _insert_acknowledged(conn, SMALL_HISTORY)
    sent = _say_steering(conn)
    before = _measure(conn, scope=SCOPE_AREA)
    assert before["count"] == 0

    _link_document(conn, 101, "AREA-PLAN")
    after = _measure(conn, scope=SCOPE_AREA)

    assert after["count"] == 1
    assert _drainable_ids(conn, scope=SCOPE_AREA) == [sent["message_id"]]
    assert after["statements"] == before["statements"]
    assert after["links"] == before["links"] == 1


def test_draining_still_renders_bodies_for_the_actionable_subset() -> None:
    conn = message_connection()
    _insert_acknowledged(conn, 30)
    _say_steering(conn, body="Blocked: parked among settled history.")
    _seat(conn, claim_id=11, session_id="s4")

    handoff = drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s4",
        claim_id=11,
        descriptor="alpha",
        now=NOW,
    )

    assert handoff["drained_count"] == 1
    assert "parked among settled history" in handoff["digest"]
    assert "close-out reporting landed" not in handoff["digest"]

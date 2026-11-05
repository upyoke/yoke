"""The batched message page answers exactly what one-message reads answer.

The page reads a whole page of messages in a fixed number of statements and
filters visibility in SQL. These tests hold it to the per-message rule it
replaced: the same rows for every caller, the same receipts as a single
read, expired receipts shown as expired before any sweep persists them, and
a statement count and handler time that do not grow with the page.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from yoke_contracts.read_detail import DETAIL_FULL
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    ROLE_VIEWER,
    grant_actor_org_role,
)
from yoke_core.domain.session_message_authorization import can_read_project
from yoke_core.domain.session_message_delivery import expire_due_recipients
from yoke_core.domain.session_message_page import read_message_page
from yoke_core.domain.session_message_queries import get_message
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.steering_message_recipients import STEERING_KIND
from runtime.api.domain.session_message_support_test_support import (
    NOW,
    message_connection,
    page_rows,
    pin_message_clocks,
    selector,
)
from runtime.api.domain.steering_role_addressed_messages_test_support import (
    _say_steering,
    _seat,
)

#: Every (actor, session) pair whose view the parity check compares.
CALLERS = (
    (10, "s1"),
    (10, "s2"),
    (10, None),
    (11, None),
    (11, "s2"),
    (12, None),
    (13, None),
    (13, "s3"),
)
#: Receipt and caller fields a page row and a single read must agree on; a
#: page row's session receipts carry a subset of a single read's columns.
SHARED = (
    "state",
    "acknowledgement_command",
    "sender_actor_label",
    "sender_actor_kind",
    "recipients",
    "actor_recipients",
    "steering_recipient",
)


@pytest.fixture(autouse=True)
def _fixed_read_clock(monkeypatch) -> None:
    pin_message_clocks(monkeypatch)


def _members():
    """The shared fixture plus the org membership person-addressed mail needs."""
    conn = message_connection()
    grant_actor_org_role(conn, actor_id=10, org_id=1, role_name=ROLE_OPERATOR)
    grant_actor_org_role(conn, actor_id=11, org_id=1, role_name=ROLE_VIEWER)
    conn.commit()
    return conn


def _send(conn, *, sender: str = "s1", sent_at=NOW, **target) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id=sender,
        selector=selector(**target),
        body="parity",
        now=sent_at,
    )["message_id"]


def _mixed_mailbox(conn) -> dict[str, str]:
    ids = {
        "to_s1": _send(conn, sender="s2", session_ids=["s1"]),
        "to_s3": _send(conn, session_ids=["s3"]),
        "to_person": _send(conn, actors=["11"]),
        "to_person_and_s1": _send(conn, actors=["Grace"], session_ids=["s1"]),
        "parked_steering": _say_steering(conn)["message_id"],
        "expired_to_s1": _send(
            conn, sender="s2", sent_at=NOW - timedelta(hours=25), session_ids=["s1"]
        ),
        "expired_to_person": _send(
            conn, sent_at=NOW - timedelta(hours=25), actors=["11"]
        ),
    }
    ids["acknowledged_to_s1"] = _send(conn, sender="s2", session_ids=["s1"])
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged',"
        "acknowledged_at=? WHERE message_id=?",
        (NOW.isoformat(), ids["acknowledged_to_s1"]),
    )
    _seat(conn, claim_id=90, session_id="s2")
    ids["seated_steering"] = _say_steering(conn)["message_id"]
    conn.commit()
    return ids


def _per_message_visible(conn, message_id: str, actor_id: int, session_id) -> bool:
    """The per-row rule the page used to apply after its query."""
    sender = conn.execute(
        "SELECT sender_actor_id FROM session_messages WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]
    roles = conn.execute(
        "SELECT recipient_kind,actor_id,seat_session_id,project_id "
        "FROM actor_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchall()
    sessions = conn.execute(
        "SELECT session_id,project_id FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchall()
    if sender == actor_id or any(
        kind == ACTOR_KIND and actor == actor_id for kind, actor, _, _ in roles
    ):
        return True
    if session_id and (
        any(row[0] == session_id for row in sessions)
        or any(
            kind == STEERING_KIND and seat == session_id for kind, _, seat, _ in roles
        )
    ):
        return True
    projects = {row[1] for row in sessions} | {
        project for kind, _, _, project in roles if kind == STEERING_KIND
    }
    return bool(projects) and all(
        can_read_project(conn, actor_id=actor_id, project_id=project)
        for project in projects
    )


def _page(conn, actor_id: int, session_id, **filters) -> list[dict]:
    return page_rows(
        conn, actor_id=actor_id, caller_session_id=session_id, limit=500, **filters
    )


def test_every_caller_sees_exactly_the_rows_the_per_message_rule_admits() -> None:
    conn = _members()
    ids = _mixed_mailbox(conn)
    for actor_id, session_id in CALLERS:
        expected = {
            message_id
            for message_id in ids.values()
            if _per_message_visible(conn, message_id, actor_id, session_id)
        }
        rows = _page(conn, actor_id, session_id)
        assert {row["message_id"] for row in rows} == expected, (actor_id, session_id)
        for row in rows:
            single = get_message(
                conn,
                message_id=row["message_id"],
                actor_id=actor_id,
                session_id=session_id,
            )
            assert len(row["recipients"]) == len(single["recipients"])
            single["recipients"] = [
                {key: receipt[key] for key in listed}
                for listed, receipt in zip(row["recipients"], single["recipients"])
            ]
            assert {key: row.get(key) for key in SHARED} == {
                key: single.get(key) for key in SHARED
            }


def test_an_expired_message_reads_expired_before_the_sweep_persists_it() -> None:
    conn = _members()
    ids = _mixed_mailbox(conn)
    expired = {ids["expired_to_s1"], ids["expired_to_person"]}

    for state in ("unacknowledged", "pending", "injected"):
        listed = {row["message_id"] for row in _page(conn, 10, "s1", state=state)}
        assert not listed & expired, state
    actionable = [row for row in _page(conn, 10, "s1") if row["needs_attention"]]
    assert not {row["message_id"] for row in actionable} & expired
    assert {row["message_id"] for row in _page(conn, 10, "s1", state="expired")} == (
        expired
    )
    for row in _page(conn, 11, None):
        if row["message_id"] == ids["expired_to_person"]:
            assert row["state"] == "expired"
    stored = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=?",
        (ids["expired_to_s1"],),
    ).fetchone()[0]
    assert stored == "pending", "a list read must not write expiry"


def test_the_sweep_persists_what_the_page_already_showed() -> None:
    conn = _members()
    ids = _mixed_mailbox(conn)
    views = [
        (actor_id, session_id, state)
        for actor_id, session_id in CALLERS
        for state in (None, "unacknowledged", "expired")
    ]

    def snapshot() -> list[list[dict]]:
        rows = [_page(conn, a, s, state=state) for a, s, state in views]
        for page in rows:
            for row in page:
                for receipt in [*row["recipients"], *row["actor_recipients"]]:
                    receipt.pop("expired_at", None)
        return rows

    before = snapshot()
    expire_due_recipients(conn, now=NOW)
    persisted = conn.execute(
        "SELECT state FROM actor_message_recipients WHERE message_id=? "
        "AND recipient_kind=?",
        (ids["expired_to_person"], ACTOR_KIND),
    ).fetchone()[0]
    assert persisted == "expired"
    assert snapshot() == before


def _statements(conn, limit: int) -> int:
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    try:
        read_message_page(
            conn, actor_id=10, caller_session_id="s2", limit=limit, detail=DETAIL_FULL
        )
    finally:
        conn.set_trace_callback(None)
    return len(seen)


def _fill(conn, count: int) -> None:
    for offset in range(count):
        _send(
            conn,
            sender="s2",
            sent_at=NOW - timedelta(minutes=offset),
            session_ids=["s1"],
            actors=["11"],
        )
    _say_steering(conn)


def test_statement_count_does_not_grow_with_the_page() -> None:
    small, large = _members(), _members()
    _fill(small, 3)
    _fill(large, 60)

    assert _statements(small, 500) == _statements(large, 500)


def test_a_two_hundred_message_page_answers_well_under_a_second() -> None:
    conn = _members()
    _fill(conn, 200)

    elapsed_reads = []
    for _ in range(3):
        started = time.perf_counter()
        page = read_message_page(conn, actor_id=10, caller_session_id="s2", limit=200)
        elapsed_reads.append(time.perf_counter() - started)
        assert page["count"] == 201

    elapsed = min(elapsed_reads)
    assert elapsed < 0.5, f"200-message page took {elapsed:.3f}s"

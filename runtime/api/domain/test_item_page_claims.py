"""The claim an item page shows is the one that holds it now.

An item detail draws the holder's own session card, so the claim behind that
card decides who a reader will go and ask. A released claim reaching it would
name somebody who handed the item back, and a superseded one would name the
holder before the current holder.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain.item_page_claims import active_item_claims
from yoke_core.domain.work_claim_targets import make_item_target


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claim_type TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            actor_id INTEGER,
            executor TEXT
        );
        CREATE TABLE actors (
            id INTEGER PRIMARY KEY,
            kind TEXT,
            name TEXT
        );
        """
    )
    conn.execute("INSERT INTO actors VALUES (2,'human','Ben')")
    conn.execute("INSERT INTO actors VALUES (3,'human','Dana')")
    return conn


def _claim(
    conn: sqlite3.Connection,
    claim_id: int,
    session_id: str,
    *,
    actor_id: int,
    released_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions VALUES (?,?,?)",
        (session_id, actor_id, "claude-code"),
    )
    conn.execute(
        "INSERT INTO work_claims VALUES (?,?,?,?,?,?,?)",
        (
            claim_id,
            session_id,
            "item",
            make_item_target(7).scope_json(),
            "exclusive",
            "2026-09-01T12:00:00Z",
            released_at,
        ),
    )


def test_a_released_claim_is_not_the_items_holder() -> None:
    conn = _connection()
    _claim(conn, 1, "session-released", actor_id=2, released_at="2026-09-01T13:00:00Z")

    assert active_item_claims(conn, [7]) == {}


def test_the_newest_live_claim_wins_over_an_earlier_one() -> None:
    conn = _connection()
    _claim(conn, 1, "session-earlier", actor_id=2, released_at="2026-09-01T13:00:00Z")
    _claim(conn, 2, "session-current", actor_id=3)

    holder = active_item_claims(conn, [7])[7]
    assert holder["session_id"] == "session-current"
    assert holder["actor_label"] == "Dana"


def test_an_unclaimed_item_reports_no_holder() -> None:
    assert active_item_claims(_connection(), [7]) == {}

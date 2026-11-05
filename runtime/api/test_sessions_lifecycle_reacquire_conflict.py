"""Conditional auto-reacquire + conflict fall-through coverage.

Reactivation auto-reacquires session_ended claims within window.
Reactivation outside window does not auto-reacquire.
Conflict with another active session falls through to advisory.

Runs against a disposable per-test Postgres database (the Yoke
authority), not an in-memory SQLite double: the reactivation module
under test now issues native ``%s`` SQL that only the Postgres backend
parses. Each test class inherits the per-test DB lifecycle from
:class:`_PgReacquireTestCase`.
"""

from __future__ import annotations

from runtime.api.sessions_lifecycle_reacquire_conflict_test_support import (
    _CREATE_EVENTS as _CREATE_EVENTS,
    _CREATE_SESSIONS as _CREATE_SESSIONS,
    _CREATE_WORK_CLAIMS as _CREATE_WORK_CLAIMS,
    _PgReacquireTestCase as _PgReacquireTestCase,
    _apply_reacquire_schema as _apply_reacquire_schema,
    _insert_released_claim as _insert_released_claim,
    _insert_session as _insert_session,
    _iso as _iso,
)


import unittest
from unittest import mock


from yoke_core.domain.sessions_lifecycle_reactivation import (
    auto_reacquire_session_ended_claims,
    emit_reactivated_with_released_claims,
)
from yoke_core.domain.work_claim_targets import make_item_target, scope_int_sql


def _insert_active_claim_other(
    conn,
    session_id: str,
    item_id: int,
) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
        (session_id, make_item_target(item_id).scope_json(), _iso(), _iso()),
    )
    conn.commit()


class TestAutoReacquireWithinWindow(_PgReacquireTestCase):
    def test_within_window_inserts_new_active_claim(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-A")
        _insert_released_claim(conn, "sess-A", 100, released_age_s=10)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn,
            "sess-A",
            reacquire_window_s=300,
        )
        self.assertEqual(len(reacquired), 1)
        self.assertEqual(reacquired[0]["scope"], {"item_id": 100})
        self.assertEqual(conflicts, [])
        active_count = conn.execute(
            "SELECT COUNT(*) FROM work_claims "
            "WHERE session_id = %s AND released_at IS NULL",
            ("sess-A",),
        ).fetchone()[0]
        self.assertEqual(active_count, 1)

    def test_reacquired_item_claim_restores_focus(self) -> None:
        """A resumed episode points at the work its claim came back to."""
        conn = self.conn
        _insert_session(conn, "sess-focus")
        _insert_released_claim(conn, "sess-focus", 101, released_age_s=10)
        # Session end archived the focus slot; the claim outlived it.
        conn.execute(
            "UPDATE harness_sessions SET current_item_id = NULL, "
            "recent_item_id = '101' WHERE session_id = %s",
            ("sess-focus",),
        )
        conn.commit()
        reacquired, _ = auto_reacquire_session_ended_claims(
            conn,
            "sess-focus",
            reacquire_window_s=300,
        )
        self.assertEqual(len(reacquired), 1)
        focus = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            ("sess-focus",),
        ).fetchone()[0]
        self.assertEqual(str(focus), "101")

    def test_unreacquired_claim_leaves_focus_empty(self) -> None:
        """Focus is claim-derived: no reacquire, no focus."""
        conn = self.conn
        _insert_session(conn, "sess-no-focus")
        _insert_released_claim(conn, "sess-no-focus", 202, released_age_s=600)
        reacquired, _ = auto_reacquire_session_ended_claims(
            conn,
            "sess-no-focus",
            reacquire_window_s=300,
        )
        self.assertEqual(reacquired, [])
        focus = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            ("sess-no-focus",),
        ).fetchone()[0]
        self.assertIsNone(focus)

    def test_outside_window_does_not_reacquire(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-B")
        # released 600s ago — outside default 300s window
        _insert_released_claim(conn, "sess-B", 200, released_age_s=600)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn,
            "sess-B",
            reacquire_window_s=300,
        )
        self.assertEqual(reacquired, [])
        self.assertEqual(conflicts, [])

    def test_conflict_with_other_session_falls_through(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-orig")
        _insert_session(conn, "sess-other")
        _insert_released_claim(conn, "sess-orig", 300, released_age_s=10)
        # Another session holds an active claim on the same item.
        _insert_active_claim_other(conn, "sess-other", 300)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn,
            "sess-orig",
            reacquire_window_s=300,
        )
        self.assertEqual(reacquired, [])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["holder_session_id"], "sess-other")

    def test_multiple_recent_releases_for_same_target_reacquire_once(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-repeat")
        _insert_released_claim(conn, "sess-repeat", 301, released_age_s=20)
        _insert_released_claim(conn, "sess-repeat", 301, released_age_s=10)
        reacquired, conflicts = auto_reacquire_session_ended_claims(
            conn,
            "sess-repeat",
            reacquire_window_s=300,
        )
        self.assertEqual(len(reacquired), 1)
        self.assertEqual(conflicts, [])
        item_id = scope_int_sql(conn, "scope", "item_id")
        active_count = conn.execute(
            "SELECT COUNT(*) FROM work_claims "
            f"WHERE session_id = %s AND {item_id} = %s AND released_at IS NULL",
            ("sess-repeat", 301),
        ).fetchone()[0]
        self.assertEqual(active_count, 1)


class TestEmitReactivatedWithReleasedClaimsReceipt(_PgReacquireTestCase):
    def test_emits_receipt_when_reacquire_or_conflict(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-C")
        _insert_released_claim(conn, "sess-C", 400, released_age_s=10)
        with (
            mock.patch("yoke_core.domain.events.emit_event") as emit_event,
            mock.patch(
                "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
            ),
        ):
            emit_reactivated_with_released_claims(
                conn,
                "sess-C",
                reacquire_window_s=300,
            )
        event_names = [call.args[0] for call in emit_event.call_args_list]
        self.assertIn("SessionReactivationReacquiredClaims", event_names)

    def test_no_receipt_when_nothing_to_reacquire(self) -> None:
        conn = self.conn
        _insert_session(conn, "sess-D")
        _insert_released_claim(conn, "sess-D", 500, released_age_s=99999)
        with (
            mock.patch("yoke_core.domain.events.emit_event") as emit_event,
            mock.patch(
                "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
            ),
        ):
            emit_reactivated_with_released_claims(
                conn,
                "sess-D",
                reacquire_window_s=300,
            )
        names = [call.args[0] for call in emit_event.call_args_list]
        self.assertNotIn("SessionReactivationReacquiredClaims", names)


if __name__ == "__main__":
    unittest.main()

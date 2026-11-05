# ruff: noqa: F401
"""Regression tests: session-end + reactivation + conduct re-entry claim gap.

Exercise the released-claim advisory around a reactivated session:
  1. Session claims an item, then ends with release reason='session_ended'.
  2. Same session is reactivated (ended_at cleared).
  3. Advisory state includes only prior session-ended claims.
  4. Conditional reacquisition remains governed by the configured time window.
"""

from __future__ import annotations

from runtime.api.sessions_lifecycle_reactivation_claims_test_support import (
    _CREATE_ACTORS as _CREATE_ACTORS,
    _CREATE_EVENTS as _CREATE_EVENTS,
    _CREATE_EVENT_REGISTRY as _CREATE_EVENT_REGISTRY,
    _CREATE_ORGANIZATIONS as _CREATE_ORGANIZATIONS,
    _CREATE_PROJECTS as _CREATE_PROJECTS,
    _CREATE_SESSIONS as _CREATE_SESSIONS,
    _CREATE_WORK_CLAIMS as _CREATE_WORK_CLAIMS,
    _ReactivationDBTest as _ReactivationDBTest,
    _apply_reactivation_schema as _apply_reactivation_schema,
    _insert_claim as _insert_claim,
    _insert_session as _insert_session,
)


import tempfile
import unittest
from pathlib import Path
from unittest import mock
from typing import Any, Dict, Optional

from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.sessions_analytics_core import (
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
)
from yoke_core.domain.sessions_lifecycle_reactivation import (
    emit_reactivated_with_released_claims,
)
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.fixtures.operating_actor import record_fixture_operating_actor
from yoke_core.domain.actors import seed_canonical_human, sole_human_actor_id
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


# ---------------------------------------------------------------------------
# Minimal schema fixture
# ---------------------------------------------------------------------------


# register_session's actor resolver runs `SELECT 1 FROM actors WHERE id = %s`
# when callers pass an explicit actor_id. An empty actors table lets that probe
# succeed cleanly; without it the missing-relation error aborts the transaction
# before the subsequent INSERT.


# Recording which actor this machine operates the universe as requires the
# universe to say which universe it is, and that answer is its single
# organization identity card. A fixture that registers sessions carries one
# for the same reason a born universe does.


def _emitted_events(conn: Any, event_name: str) -> list:
    rows = conn.execute(
        "SELECT * FROM events WHERE event_name = %s", (event_name,)
    ).fetchall()
    return [dict(r) for r in rows]


class TestEmitReactivatedWithReleasedClaims(_ReactivationDBTest):
    def test_no_event_when_no_session_ended_claims(self) -> None:
        """No advisory event when all claims are active or have other release reasons."""
        conn = self.conn
        _insert_session(conn, "sess-1")
        # Active claim (not released)
        _insert_claim(conn, "sess-1", 100, released=False)
        # Released for a different reason
        _insert_claim(conn, "sess-1", 101, released=True, release_reason="completed")

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-1")

        self.assertEqual(result, [])
        emit_event.assert_not_called()
        self.assertEqual(
            _emitted_events(conn, EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS), []
        )

    def test_emits_event_for_session_ended_claims(self) -> None:
        """Advisory event triggered when prior session-ended claims exist."""
        conn = self.conn
        _insert_session(conn, "sess-2")
        _insert_claim(
            conn, "sess-2", 200, released=True, release_reason="session_ended"
        )

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-2")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target_kind"], "item")
        self.assertEqual(result[0]["scope"], {"item_id": 200})
        emit_event.assert_called_once()
        event_name = emit_event.call_args.args[0]
        event_kwargs = emit_event.call_args.kwargs
        self.assertEqual(event_name, EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS)
        self.assertEqual(event_kwargs["session_id"], "sess-2")
        self.assertEqual(event_kwargs["context"]["released_claim_count"], 1)
        self.assertEqual(
            event_kwargs["context"]["released_claims"],
            [{"target_kind": "item", "scope": {"item_id": 200}}],
        )

    def test_release_outside_window_does_not_insert_new_work_claim(self) -> None:
        """A release outside the reacquisition window remains advisory-only."""
        conn = self.conn
        _insert_session(conn, "sess-3")
        _insert_claim(
            conn, "sess-3", 300, released=True, release_reason="session_ended"
        )

        before = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = 'sess-3'"
        ).fetchone()[0]

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ):
            emit_reactivated_with_released_claims(conn, "sess-3")

        after = conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE session_id = 'sess-3'"
        ).fetchone()[0]

        self.assertEqual(
            before,
            after,
            "An out-of-window release must not be reacquired.",
        )

    def test_multiple_session_ended_claims_all_reported(self) -> None:
        """All prior session-ended claims appear in the event payload."""
        conn = self.conn
        _insert_session(conn, "sess-4")
        _insert_claim(
            conn, "sess-4", 401, released=True, release_reason="session_ended"
        )
        _insert_claim(
            conn, "sess-4", 402, released=True, release_reason="session_ended"
        )

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-4")

        self.assertEqual(len(result), 2)
        item_ids = {r["scope"]["item_id"] for r in result}
        self.assertEqual(item_ids, {401, 402})
        emit_event.assert_called_once()
        claims = emit_event.call_args.kwargs["context"]["released_claims"]
        self.assertEqual(
            {claim["scope"]["item_id"] for claim in claims},
            {401, 402},
        )

    def test_active_claim_not_included_in_advisory(self) -> None:
        """Active claim is not listed in reactivation advisory."""
        conn = self.conn
        _insert_session(conn, "sess-5")
        _insert_claim(
            conn, "sess-5", 500, released=True, release_reason="session_ended"
        )
        # This claim is still active (reactivation may have already occurred earlier)
        _insert_claim(conn, "sess-5", 501, released=False)

        with mock.patch(
            "yoke_core.domain.sessions_lifecycle_reactivation._emit_session_event"
        ) as emit_event:
            result = emit_reactivated_with_released_claims(conn, "sess-5")

        item_ids = {r["scope"]["item_id"] for r in result}
        self.assertIn(500, item_ids)
        self.assertNotIn(501, item_ids)
        emit_event.assert_called_once()
        claims = emit_event.call_args.kwargs["context"]["released_claims"]
        self.assertEqual([claim["scope"]["item_id"] for claim in claims], [500])


if __name__ == "__main__":
    unittest.main()

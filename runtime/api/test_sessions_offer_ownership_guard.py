"""Unit tests for the runtime ownership guard (Task 007).

Covers the four canonical owned/not-owned shapes from the spec:

1. **Self-claim owned** — the calling session holds a live unreleased
   ``work_claims`` row on the item. ``owned=True``, no defense needed.
2. **Defense-in-flight owned** — the calling session released its claim
   with a non-terminal intent, and the recent-owner exclusion from
   Task 003 still names the session as the prior owner.
3. **No-claim-no-defense not-owned** — no claim and no defense; the
   guard returns ``owned=False`` with no holder.
4. **Other-session-holds-claim not-owned** — another live session holds
   the claim; the guard returns ``owned=False`` and names that holder.

The fixtures reuse :mod:`runtime.api.routed_ownership_test_helpers` so
this regression sits on the same minimal schema as
``test_routed_ownership_release_gap.py``.
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure the repo root is importable when this module runs directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.sessions_offer_ownership_guard import (
    OwnershipGuardResult,
    evaluate_ownership_guard,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from runtime.api.routed_ownership_test_helpers import (
    SESSION_A,
    SESSION_B,
    SYNTHETIC_ITEM_ID,
    SYNTHETIC_ITEM_REF,
    _ReleaseGapDbCase,
    build_release_gap_fixture,
    register_live_session,
    seed_item,
)


class TestEvaluateOwnershipGuard(_ReleaseGapDbCase):
    """Behavioural contract for :func:`evaluate_ownership_guard`."""

    def test_self_claim_owned(self) -> None:
        """Session A holds the live claim on the item -> owned=True."""
        conn = self.make_db()
        seed_item(conn)
        register_live_session(
            conn, SESSION_A, current_item_id=str(SYNTHETIC_ITEM_ID),
        )
        claim_work(conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_REF)

        result = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID,
        )

        self.assertIsInstance(result, OwnershipGuardResult)
        self.assertTrue(
            result.owned,
            "Live unreleased self-claim must satisfy the guard.",
        )
        self.assertEqual(result.holder_session_id, SESSION_A)
        self.assertIsNotNone(result.claim_id)
        self.assertFalse(result.defense_in_flight)

    def test_defense_in_flight_owned(self) -> None:
        """Session A released non-terminally; recent-owner defense covers it."""
        conn = self.make_db()
        # build_release_gap_fixture stages: seed item + register A and B,
        # claim by A, non-terminal release by A, seed WorkReleased event.
        build_release_gap_fixture(conn)

        result = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID,
        )

        self.assertTrue(
            result.owned,
            "Recent-owner defense must keep session A owning the item "
            "across a non-terminal release while its frame is live.",
        )
        self.assertEqual(result.holder_session_id, SESSION_A)
        self.assertTrue(
            result.defense_in_flight,
            "defense_in_flight must be True when ownership flows from "
            "the routed-ownership exclusion rather than a live claim.",
        )
        self.assertIsNotNone(result.claim_id)

    def test_no_claim_no_defense_not_owned(self) -> None:
        """No claim history at all -> owned=False with no holder."""
        conn = self.make_db()
        seed_item(conn)
        register_live_session(conn, SESSION_A)

        result = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID,
        )

        self.assertFalse(
            result.owned,
            "Session with no claim and no defense must not own the item.",
        )
        self.assertIsNone(result.holder_session_id)
        self.assertIsNone(result.claim_id)
        self.assertFalse(result.defense_in_flight)

    def test_other_session_holds_claim_not_owned(self) -> None:
        """Session B holds the live claim -> session A not owned, B named."""
        conn = self.make_db()
        seed_item(conn)
        register_live_session(conn, SESSION_A)
        register_live_session(
            conn, SESSION_B, current_item_id=str(SYNTHETIC_ITEM_ID),
        )
        claim_work(conn, session_id=SESSION_B, item_id=SYNTHETIC_ITEM_REF)

        result = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID,
        )

        self.assertFalse(
            result.owned,
            "Session A must not own an item another session live-claims.",
        )
        self.assertEqual(
            result.holder_session_id, SESSION_B,
            "holder_session_id must name the current live claim holder "
            "so callers can render a useful diagnosis.",
        )
        self.assertIsNotNone(result.claim_id)
        self.assertFalse(result.defense_in_flight)

    def test_missing_inputs_return_not_owned(self) -> None:
        """Empty session_id or zero item_id must short-circuit safely."""
        conn = self.make_db()
        seed_item(conn)

        empty_session = evaluate_ownership_guard(
            conn, session_id="", item_id=SYNTHETIC_ITEM_ID,
        )
        self.assertFalse(empty_session.owned)

        zero_item = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=0,
        )
        self.assertFalse(zero_item.owned)

    def test_missing_schema_falls_back_to_not_owned(self) -> None:
        """Missing claim/session tables -> owned=False (graceful)."""
        from runtime.api.fixtures import pg_testdb

        name = pg_testdb.create_test_database()
        bare = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name,
        )
        try:
            result = evaluate_ownership_guard(
                bare, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID,
            )
        finally:
            bare.close()

        self.assertFalse(
            result.owned,
            "Operational errors (missing tables) must surface as "
            "owned=False rather than propagate.",
        )
        self.assertIsNone(result.holder_session_id)


if __name__ == "__main__":
    unittest.main()

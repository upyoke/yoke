"""End-to-end ownership-guard regression for AC-11.

Pairs with :mod:`test_sessions_offer_ownership_guard` (unit shapes) and
:mod:`test_routed_ownership_release_gap` (FrontierComputed + offer
defense). This file owns the AC-11 SM-equivalent fixture: session A is
routed, loses ownership mid-chain (claim reclaimed, session B takes the
canonical mutex), and session A's loop calls
:func:`evaluate_ownership_guard` before issuing the next item-scoped
dispatch. The guard returns ``owned=False`` and the loop records a
``handler_outcome='blocked'`` chain checkpoint instead of dispatching —
proving the runtime guard is the runtime defense, not prose-only.

Split into its own file so
``runtime/api/test_routed_ownership_release_gap.py`` stays inside the
350-line file-line-check cap; the helpers from
:mod:`runtime.api.routed_ownership_test_helpers` are shared with that
sibling regression.
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure the repo root is importable when this module runs directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.sessions_lifecycle_release import (
    release_work_claim_for_execution,
)
from yoke_core.domain.sessions_offer_ownership_guard import (
    evaluate_ownership_guard,
)
from yoke_core.domain.sessions_queries_chain import update_chain_checkpoint
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.routed_ownership_test_helpers import (
    SESSION_A,
    SESSION_B,
    SYNTHETIC_ITEM_ID,
    SYNTHETIC_ITEM_REF,
    _ReleaseGapDbCase,
    register_live_session,
    seed_item,
)


class TestOwnershipGuardEndToEnd(_ReleaseGapDbCase):
    """AC-11 — guard catches mid-chain claim loss and refuses re-dispatch."""

    def test_session_a_loses_claim_mid_chain_no_duplicate_dispatch(
        self,
    ) -> None:
        conn = self.make_db()
        seed_item(conn)
        register_live_session(
            conn, SESSION_A, current_item_id=str(SYNTHETIC_ITEM_ID))
        register_live_session(conn, SESSION_B)
        claim_work(conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_REF)

        before = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID)
        self.assertTrue(before.owned, "pre-loss self-claim must own")

        # Mid-chain: session A's claim is reclaimed; session B takes it.
        release_work_claim_for_execution(
            conn, SESSION_A, make_item_target(SYNTHETIC_ITEM_ID), "reclaimed")
        claim_work(conn, session_id=SESSION_B, item_id=SYNTHETIC_ITEM_REF)

        after = evaluate_ownership_guard(
            conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID)
        self.assertFalse(after.owned, "guard must refuse stale resume")
        self.assertEqual(
            after.holder_session_id, SESSION_B,
            "Guard surfaces the current live holder for diagnosis.",
        )
        self.assertFalse(after.defense_in_flight)

        # Session A's loop records a non-chainable terminal checkpoint
        # instead of dispatching — the AC-6 runtime contract.
        checkpoint = update_chain_checkpoint(
            conn, SESSION_A, step=2, action="resume",
            chainable=False, handler_outcome="blocked",
            item_id=str(SYNTHETIC_ITEM_ID))
        self.assertEqual(checkpoint["handler_outcome"], "blocked")
        self.assertEqual(checkpoint["chainable"], False)

        # Defense-in-depth: no fresh live claim row on the item for
        # session A — duplicate dispatch did not land.
        rows = conn.execute(
            "SELECT id FROM work_claims WHERE session_id = %s "
            "AND target_kind='item' AND item_id = %s "
            "AND released_at IS NULL",
            (SESSION_A, SYNTHETIC_ITEM_ID)).fetchall()
        self.assertEqual(len(rows), 0, "no duplicate live claim on item")


if __name__ == "__main__":
    unittest.main()

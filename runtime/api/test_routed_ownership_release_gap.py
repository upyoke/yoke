"""A persisted claim checkpoint protects unfinished routed work from reassignment."""

from __future__ import annotations

import os
import sys
import unittest


# Ensure the repo root is importable when this module runs directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier_compute import compute_frontier
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.sessions_lifecycle_release import release_work_claim_for_execution
from yoke_core.domain.sessions_queries_chain import update_chain_checkpoint
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.routed_ownership_test_helpers import (
    SESSION_A,
    SESSION_B,
    SYNTHETIC_ITEM_ID,
    _ReleaseGapDbCase,
    build_release_gap_fixture,
    register_live_session,
    seed_item,
)


class TestRoutedOwnershipReleaseGap(_ReleaseGapDbCase):
    """two-session duplicate routing window regression.

    Both tests FAIL on the release-gap worktree before Tasks 003 and 005
    land (defense does not yet cover non-terminal release intents) and
    PASS once those tasks land. Engineer / Tester treat the FAIL here
    as baseline evidence that the bug is real.
    """

    def test_frontier_defends_non_terminal_release_gap(self) -> None:
        """Frontier MUST exclude an item whose live owner just released
        with ``readiness-check-blocked``; session B sees it as blocked,
        with telemetry naming the prior owner."""
        conn = self.make_db()
        build_release_gap_fixture(conn)

        result = compute_frontier(conn, project_scope=["yoke"], session_id=SESSION_B)
        runnable_ids = {item.item_id for item in result.runnable}
        blocked_ids = {item.item_id for item in result.blocked}

        self.assertNotIn(
            SYNTHETIC_ITEM_ID,
            runnable_ids,
            (
                "Session B's frontier still treats the routed item as "
                "runnable after session A released the underlying "
                "claim with a non-terminal intent — the YOK-1670 "
                "duplicate routing window is still open."
            ),
        )
        self.assertIn(
            SYNTHETIC_ITEM_ID,
            blocked_ids,
            (
                "Session B's frontier must surface the routed item in "
                "the blocked partition with a defense reason naming "
                "the prior owner — operator triage relies on this."
            ),
        )

        defended = next(
            (item for item in result.blocked if item.item_id == SYNTHETIC_ITEM_ID), None
        )
        self.assertIsNotNone(defended)
        joined_reasons = " ".join(defended.blocked_reasons)
        self.assertIn(
            SESSION_A,
            joined_reasons,
            (
                "Blocked-reason rendering must name the prior owner "
                f"session id ({SESSION_A}) so the operator can trace "
                "the route-defense edge back to the live handler."
            ),
        )


class TestRefineCheckpointBeforeReleaseSequence(_ReleaseGapDbCase):
    """task 006 SM-3 spine — refine's stanza order is sound.

    Refine writes a ``chainable=False`` checkpoint BEFORE calling
    ``release_work_claim_for_execution`` with the non-terminal intent
    ``readiness-check-blocked``. Task 004's runtime precondition reads
    the persisted checkpoint and allows the release because
    ``chainable=False`` is durable terminal evidence. This drives the
    production helpers so the skill prose edits in task 006 stay valid
    as the precondition evolves.
    """

    def test_chainable_false_checkpoint_then_release_succeeds(self) -> None:
        conn = self.make_db()
        seed_item(conn)
        register_live_session(conn, SESSION_A, current_item_id=str(SYNTHETIC_ITEM_ID))
        claim_work(conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_ID)

        checkpoint = update_chain_checkpoint(
            conn,
            SESSION_A,
            step=1,
            action="refine",
            chainable=False,
            handler_outcome="blocked",
            item_id=str(SYNTHETIC_ITEM_ID),
        )
        self.assertEqual(checkpoint["chainable"], False)
        self.assertEqual(checkpoint["handler_outcome"], "blocked")

        result = release_work_claim_for_execution(
            conn,
            SESSION_A,
            make_item_target(SYNTHETIC_ITEM_ID),
            "readiness-check-blocked",
        )
        self.assertTrue(
            result["released"],
            "release_work_claim_for_execution must succeed when the "
            "session has persisted a chainable=False checkpoint before "
            "the readiness-check-blocked release — structural sequencing "
            "refine relies on.",
        )
        self.assertEqual(result["reason_intent"], "readiness-check-blocked")
        self.assertEqual(result["reason_stored"], "released")

        target = make_item_target(SYNTHETIC_ITEM_ID)
        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id = %s AND target_kind = %s AND scope = %s",
            (SESSION_A, target.kind, target.scope_json()),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(
            row["released_at"],
            "work_claims.released_at must be stamped after a precondition-allowed release.",
        )


if __name__ == "__main__":
    unittest.main()

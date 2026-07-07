"""Regression spine for the two-session duplicate routing window.

Reproduces the 2026-05-13 incident timeline. Session A
(``019e1f0d-7f82-72d2-85ee-b46947b2a6fd``) was routed to an item and
held work claim ``1722``. Session A released that claim with
``release_reason_intent='readiness-check-blocked'`` while its routed
handler frame remained live and item-scoped recovery was still in
flight. Session B (``019e1f0a-a6a2-7321-835f-9772a881820b``) then saw
the item as runnable, claimed it as work claim ``1725``, and ran it to
completion in parallel with session A.

The two test cases assert the structural invariant the release-gap defense
establishes: once Yoke routes item ``N`` to a live session ``S``, no
other live session may be offered or claim item ``N`` until ``S``
reaches a terminal boundary for that routed frame — even when ``S``
has released its underlying ``work_claims`` row with a non-terminal
release intent.

Both cases drive the production helpers
:func:`release_work_claim_for_execution`,
:func:`compute_frontier`, and :func:`session_offer_with_ownership` and
the real :func:`emit_event` write path so the regression captures the
shape that scheduler assignability actually consumes — no mocked event
emission, no hand-rolled SQL release. The item id is the synthetic
``9999`` so drifting backlog state cannot accidentally satisfy or
invalidate the regression; the reference lives only in this
docstring per the AGENTS.md "no hardcoded drifting IDs" rule.

This file is the FAIL → PASS spine for Tasks 003 + 005. On the
release-gap worktree branch before those tasks land, both tests FAIL
(session B's frontier counts the item as runnable and
``session-offer`` hands the item to session B). Once Task 003 widens
the recent-owner defense to non-terminal release intents and Task 005
preserves offer-envelope ownership state, both tests PASS.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable when this module runs directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier_compute import compute_frontier
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.sessions_lifecycle_release import (
    release_work_claim_for_execution,
)
from yoke_core.domain.sessions_offer import session_offer_with_ownership
from yoke_core.domain.sessions_queries_chain import update_chain_checkpoint
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.routed_ownership_test_helpers import (
    SESSION_A,
    SESSION_B,
    SYNTHETIC_ITEM_ID,
    SYNTHETIC_ITEM_REF,
    WORKSPACE,
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
    as the AC-2 baseline evidence that the bug is real.
    """

    def test_frontier_defends_non_terminal_release_gap(self) -> None:
        """Frontier MUST exclude an item whose live owner just released
        with ``readiness-check-blocked``; session B sees it as blocked,
        with telemetry naming the prior owner."""
        conn = self.make_db()
        build_release_gap_fixture(conn)

        result = compute_frontier(
            conn, project_scope=["yoke"], session_id=SESSION_B,
        )
        runnable_ids = {item.item_id for item in result.runnable}
        blocked_ids = {item.item_id for item in result.blocked}

        self.assertNotIn(
            SYNTHETIC_ITEM_REF,
            runnable_ids,
            (
                "Session B's frontier still treats the routed item as "
                "runnable after session A released the underlying "
                "claim with a non-terminal intent — the YOK-1670 "
                "duplicate routing window is still open."
            ),
        )
        self.assertIn(
            SYNTHETIC_ITEM_REF,
            blocked_ids,
            (
                "Session B's frontier must surface the routed item in "
                "the blocked partition with a defense reason naming "
                "the prior owner — operator triage relies on this."
            ),
        )

        defended = next(
            (item for item in result.blocked
             if item.item_id == SYNTHETIC_ITEM_REF),
            None,
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

    def test_session_offer_refuses_non_terminal_release_gap(self) -> None:
        """``session_offer_with_ownership`` MUST NOT hand the routed
        item to session B while session A's routed frame is live; the
        action hint is ``no_work`` (or names a different item) and no
        fresh claim row is acquired on the routed item."""
        conn = self.make_db()
        build_release_gap_fixture(conn)

        offer = session_offer_with_ownership(
            conn,
            session_id=SESSION_B,
            executor="claude-code",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace=WORKSPACE,
            step=1,
            project_scope=["yoke"],
        )

        new_claim = offer.get("new_claim")
        action_hint = offer.get("action_hint")

        if new_claim is not None:
            self.assertNotEqual(
                str(new_claim.get("item_id")),
                str(SYNTHETIC_ITEM_ID),
                (
                    "Session B was handed the routed item even though "
                    "session A's routed frame is still live with a "
                    "non-terminal release intent — duplicate routed "
                    "ownership is observable."
                ),
            )
        else:
            self.assertIn(
                action_hint,
                ("no_work", "resume"),
                (
                    f"Expected action_hint='no_work' (or 'resume'); "
                    f"got {action_hint!r}; routed item must not have "
                    "been offered."
                ),
            )

        # Defense-in-depth: no live claim row on the routed item should
        # exist for session B regardless of the offer return shape.
        row = conn.execute(
            "SELECT id FROM work_claims WHERE session_id = %s "
            "AND target_kind = 'item' AND item_id = %s "
            "AND released_at IS NULL",
            (SESSION_B, SYNTHETIC_ITEM_ID),
        ).fetchone()
        self.assertIsNone(
            row,
            (
                "Session B acquired a live work_claims row on the "
                "routed item — the structural duplicate routed "
                "ownership window from YOK-1670 is observable."
            ),
        )

    def test_frontier_computed_envelope_carries_routed_ownership_evidence(
        self,
    ) -> None:
        """FR-7 envelope evidence.

        Parses the ``FrontierComputed`` event envelope produced by the
        session-B frontier sweep and asserts the per-defended-item
        detail dict under ``$.context.excluded_routed_ownership[0]``
        carries all five FR-7 fields. Uses ``YOKE_EVENTS_CAPTURE`` so
        the production emitter writes the envelope to a temp file the
        test parses — no production-code mock.
        """
        conn = self.make_db()
        build_release_gap_fixture(conn)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False,
        ) as handle:
            capture_path = handle.name
        prev_capture = os.environ.get("YOKE_EVENTS_CAPTURE")
        prev_file = os.environ.get("YOKE_EVENTS_FILE")
        os.environ["YOKE_EVENTS_CAPTURE"] = "1"
        os.environ["YOKE_EVENTS_FILE"] = capture_path
        try:
            compute_frontier(
                conn, project_scope=["yoke"], session_id=SESSION_B,
            )
        finally:
            if prev_capture is None:
                os.environ.pop("YOKE_EVENTS_CAPTURE", None)
            else:
                os.environ["YOKE_EVENTS_CAPTURE"] = prev_capture
            if prev_file is None:
                os.environ.pop("YOKE_EVENTS_FILE", None)
            else:
                os.environ["YOKE_EVENTS_FILE"] = prev_file

        envelopes = []
        with open(capture_path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    envelopes.append(json.loads(stripped))
        os.unlink(capture_path)

        frontier_envelopes = [
            env for env in envelopes
            if env.get("event_name") == "FrontierComputed"
        ]
        self.assertGreaterEqual(
            len(frontier_envelopes), 1,
            "No FrontierComputed envelope captured for session B's sweep.",
        )
        context = frontier_envelopes[-1].get("context") or {}
        self.assertGreaterEqual(
            context.get("excluded_routed_ownership_count", 0), 1,
            "FrontierComputed.context.excluded_routed_ownership_count "
            "must be >=1 with the routed item defended.",
        )
        details = context.get("excluded_routed_ownership") or []
        self.assertGreaterEqual(
            len(details), 1,
            "FrontierComputed.context.excluded_routed_ownership must "
            "carry per-defended-item detail dicts.",
        )
        first = details[0]
        for required in (
            "prior_owner_session_id",
            "latest_claim_id",
            "release_reason_intent",
            "defense_class",
            "checkpoint_outcome",
        ):
            self.assertIn(
                required, first,
                f"FR-7 evidence field {required!r} missing from "
                f"FrontierComputed envelope; got keys {sorted(first.keys())}",
            )
        self.assertIsInstance(first["prior_owner_session_id"], str)
        self.assertIsInstance(first["latest_claim_id"], int)
        self.assertIsInstance(first["release_reason_intent"], str)
        self.assertIn(
            first["defense_class"],
            ("session_ended", "non_terminal_intent"),
            f"defense_class must be a closed-set value; got "
            f"{first['defense_class']!r}",
        )
        # checkpoint_outcome may be None when no chain checkpoint exists.
        if first["checkpoint_outcome"] is not None:
            self.assertIsInstance(first["checkpoint_outcome"], str)


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
        register_live_session(
            conn, SESSION_A, current_item_id=str(SYNTHETIC_ITEM_ID))
        claim_work(conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_REF)

        checkpoint = update_chain_checkpoint(
            conn, SESSION_A, step=1, action="refine",
            chainable=False, handler_outcome="blocked",
            item_id=str(SYNTHETIC_ITEM_ID))
        self.assertEqual(checkpoint["chainable"], False)
        self.assertEqual(checkpoint["handler_outcome"], "blocked")

        result = release_work_claim_for_execution(
            conn, SESSION_A, make_item_target(SYNTHETIC_ITEM_ID),
            "readiness-check-blocked")
        self.assertTrue(
            result["released"],
            "release_work_claim_for_execution must succeed when the "
            "session has persisted a chainable=False checkpoint before "
            "the readiness-check-blocked release — structural sequencing "
            "refine relies on.",
        )
        self.assertEqual(result["reason_intent"], "readiness-check-blocked")
        self.assertEqual(result["reason_stored"], "released")

        row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id = %s "
            "AND target_kind='item' AND item_id = %s",
            (SESSION_A, SYNTHETIC_ITEM_ID),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(
            row["released_at"],
            "work_claims.released_at must be stamped after a "
            "precondition-allowed release.")


if __name__ == "__main__":
    unittest.main()

"""compute_schedule tests for the shared frontier-step scheduler — selection,
ranking, lane filtering, claim states."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.scheduler import (
    ClaimState,
    NextStep,
    _evaluate_claim_states,
    compute_schedule,
)

# Re-export the fixture so pytest discovers it in this module.
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    _create_sml_files,
    _item_num,
    scheduler_db,
)


class TestComputeSchedule:
    """Verify the shared scheduler produces correct results."""

    def test_schedule_has_project(self, scheduler_db):
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert result.project_scope == [1]

    def test_schedule_has_sml_state(self, scheduler_db):
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert result.sml_state.coherent is True

    def test_schedule_selects_highest_ranked(self, scheduler_db):
        """selected_step is the highest-ranked assignable step."""
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert result.selected_step is not None
        assert result.selected_step.rank == 0

    def test_schedule_skips_conduct_items_outside_wip_cap(self, scheduler_db):
        """CONDUCT items (epics) outside WIP cap are skipped; non-CONDUCT
        items (SHEPHERD, REFINE, ADVANCE, USHER) are still selectable.

        With the gap-1 fix, only NextStep.CONDUCT is filtered by
        conduct_eligible_ids.  ADVANCE (issue-workflow-type) passes through.
        We verify the WIP filter by checking that the selected item is NOT
        a CONDUCT step when WIP is full.
        """
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(
            scheduler_db["conn"],
            project_scope=["yoke"],
            wip_cap=1,
            workspace=scheduler_db["tmp_dir"],
        )

        assert result.selected_step is not None
        # The selected step must NOT be CONDUCT when WIP is saturated
        # .  ADVANCE, SHEPHERD,
        # REFINE, and USHER are all acceptable.
        assert result.selected_step.next_step != NextStep.CONDUCT

    def test_schedule_advance_not_blocked_by_conduct_wip_cap(self, scheduler_db):
        """Issue ADVANCE items must NOT be filtered by conduct_eligible_ids.

        Regression test for simulation gap #1: the selection loop
        previously applied the conduct_eligible_ids filter to both CONDUCT and
        ADVANCE next_steps.  Issue items routed to ADVANCE don't go through
        the conduct pipeline, so they must pass through unfiltered even when
        the WIP cap is exhausted.
        """
        conn = scheduler_db["conn"]
        # Insert an issue in implementing (routes to ADVANCE)
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, created_at, updated_at, source, frozen)
               VALUES (100, 'Implementing issue', 'issue', 'implementing',
                       'high', 1, 100, '2026-03-01', '2026-03-01',
                       'user', 0)"""
        )
        # Fill WIP with active epics so conduct_eligible is empty
        for i in range(101, 106):
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority, project_id,
                    project_sequence, created_at, updated_at, source, frozen)
                   VALUES (%s, %s, 'epic', 'implementing', 'medium', 1, %s,
                           '2026-03-01', '2026-03-01', 'user', 0)""",
                (i, f"Active epic {i}", i),
            )
        conn.commit()

        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(
            conn, project_scope=["yoke"], wip_cap=0,
            workspace=scheduler_db["tmp_dir"],
        )

        # The implementing issue should still be selectable as ADVANCE
        advance_steps = [
            s for s in result.ranked_steps
            if s.item_id == "YOK-100" and s.next_step == NextStep.ADVANCE
        ]
        assert len(advance_steps) == 1, "Implementing issue must appear as ADVANCE"

        # With wip_cap=0, no CONDUCT items should be selected, but the
        # ADVANCE item should be selected (or a non-conduct item like
        # SHEPHERD/REFINE/USHER).
        if result.selected_step is not None:
            if result.selected_step.next_step == NextStep.CONDUCT:
                pytest.fail(
                    "CONDUCT item selected despite wip_cap=0 — "
                    "conduct_eligible should be empty"
                )

    def test_schedule_type_aware_routing(self, scheduler_db):
        """Issues in idea get refine, epics in idea also get refine."""
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])

        step_map = {s.item_id: s for s in result.ranked_steps}

        # Issue in idea -> refine
        if "YOK-2" in step_map:
            assert step_map["YOK-2"].next_step == NextStep.REFINE

        # Epic in idea -> refine
        if "YOK-3" in step_map:
            assert step_map["YOK-3"].next_step == NextStep.REFINE

        # Issue in ready -> advance (AC-20: conduct rejects issues)
        if "YOK-1" in step_map:
            assert step_map["YOK-1"].next_step == NextStep.ADVANCE

        # Issue in passed -> usher
        if "YOK-5" in step_map:
            assert step_map["YOK-5"].next_step == NextStep.USHER

    def test_schedule_blocked_items_have_wait(self, scheduler_db):
        """Blocked items have next_step=WAIT."""
        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])

        for step in result.blocked_steps:
            assert step.next_step == NextStep.WAIT

    def test_schedule_deterministic(self, scheduler_db):
        """Same DB state produces identical schedule."""
        _create_sml_files(scheduler_db["tmp_dir"])
        r1 = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        r2 = compute_schedule(scheduler_db["conn"], project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])

        ids1 = [s.item_id for s in r1.ranked_steps]
        ids2 = [s.item_id for s in r2.ranked_steps]
        assert ids1 == ids2

    def test_schedule_claim_state_self(self, scheduler_db):
        """Items claimed by offering session get CLAIMED_BY_SELF."""
        conn = scheduler_db["conn"]
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-1', 'DARIUS', 'anthropic', 'claude', '/tmp', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-1', 'item', 1, 'exclusive', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')"""
        )
        conn.commit()

        _create_sml_files(scheduler_db["tmp_dir"])
        result = compute_schedule(conn, project_scope=["yoke"], session_id="sess-1", workspace=scheduler_db["tmp_dir"])

        step_map = {s.item_id: s for s in result.ranked_steps}
        if "YOK-1" in step_map:
            assert step_map["YOK-1"].claim_state == ClaimState.CLAIMED_BY_SELF

    def test_schedule_claim_state_stale_by_heartbeat(self, scheduler_db):
        """Heartbeat-stale claims are treated as reclaimable stale claims."""
        conn = scheduler_db["conn"]
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-stale', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-stale', 'item', 1, 'exclusive', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.commit()

        claims = _evaluate_claim_states(conn, ["YOK-1"])
        assert claims["YOK-1"] == ClaimState.CLAIMED_BY_STALE

    def test_schedule_selects_stale_claimed_item(self, scheduler_db):
        """scheduler selects highest-ranked CLAIMED_BY_STALE item
        instead of skipping to a lower-ranked UNCLAIMED item."""
        conn = scheduler_db["conn"]
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-stale', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )

        # First determine which item naturally ranks first so we can put
        # a stale claim on it and verify it is still selectable.
        _create_sml_files(scheduler_db["tmp_dir"])
        baseline = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert baseline.selected_step is not None
        top_item = baseline.selected_step.item_id

        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-stale', 'item', %s, 'exclusive', %s, %s)""",
            (_item_num(top_item), stale_iso, stale_iso),
        )
        conn.commit()

        result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])

        # Previously the scheduler would skip CLAIMED_BY_STALE items
        # and select a lower-ranked unclaimed item instead.
        assert result.selected_step is not None
        assert result.selected_step.item_id == top_item
        assert result.selected_step.claim_state == ClaimState.CLAIMED_BY_STALE

    def test_schedule_claim_state_ended_session(self, scheduler_db):
        """claims from ended sessions are CLAIMED_BY_STALE."""
        conn = scheduler_db["conn"]
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, ended_at, offered_at, last_heartbeat)
               VALUES ('sess-ended', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')""",
            (now_iso,),
        )

        # Determine top-ranked item, then claim it with an ended session.
        _create_sml_files(scheduler_db["tmp_dir"])
        baseline = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert baseline.selected_step is not None
        top_item = baseline.selected_step.item_id

        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-ended', 'item', %s, 'exclusive', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')""",
            (_item_num(top_item),),
        )
        conn.commit()

        claims = _evaluate_claim_states(conn, [top_item])
        assert claims[top_item] == ClaimState.CLAIMED_BY_STALE

        # And the scheduler still selects it
        result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert result.selected_step is not None
        assert result.selected_step.item_id == top_item

    def test_schedule_claim_state_15min_is_live_not_selected(self, scheduler_db):
        """15-min heartbeat: CLAIMED_BY_OTHER_LIVE, scheduler picks next item."""
        conn = scheduler_db["conn"]
        live_iso = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-15min', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (live_iso, live_iso),
        )

        _create_sml_files(scheduler_db["tmp_dir"])
        baseline = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert baseline.selected_step is not None
        top_item = baseline.selected_step.item_id

        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-15min', 'item', %s, 'exclusive', %s, %s)""",
            (_item_num(top_item), live_iso, live_iso),
        )
        conn.commit()

        claims = _evaluate_claim_states(conn, [top_item])
        assert claims[top_item] == ClaimState.CLAIMED_BY_OTHER_LIVE

        result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        if result.selected_step is not None:
            assert result.selected_step.item_id != top_item

    def test_schedule_claim_state_25min_is_stale_selected(self, scheduler_db):
        """25-min heartbeat: CLAIMED_BY_STALE, scheduler selects the item."""
        conn = scheduler_db["conn"]
        stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=25)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            """INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-25min', 'DARIUS', 'anthropic', 'claude', '/tmp', %s, %s)""",
            (stale_iso, stale_iso),
        )

        _create_sml_files(scheduler_db["tmp_dir"])
        baseline = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert baseline.selected_step is not None
        top_item = baseline.selected_step.item_id

        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-25min', 'item', %s, 'exclusive', %s, %s)""",
            (_item_num(top_item), stale_iso, stale_iso),
        )
        conn.commit()

        claims = _evaluate_claim_states(conn, [top_item])
        assert claims[top_item] == ClaimState.CLAIMED_BY_STALE

        result = compute_schedule(conn, project_scope=["yoke"], workspace=scheduler_db["tmp_dir"])
        assert result.selected_step is not None
        assert result.selected_step.item_id == top_item
        assert result.selected_step.claim_state == ClaimState.CLAIMED_BY_STALE

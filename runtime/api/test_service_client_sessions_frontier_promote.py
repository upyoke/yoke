"""Promotion regression for build_frontier_state_from_schedule.

When chain skip-memory zeros out the scheduler's top pick, the frontier
builder must walk ``schedule.ranked_steps`` and promote the next entry
that passes ``is_assignable_claim_state`` and is not itself in
``skip_memory_item_ids``. The promoted entry's metadata populates
``selected_item`` and ``scheduler_context`` so the ``/yoke do`` charge
dispatch path keeps working when the scheduler's first pick is filtered.

This sibling test module owns the promotion regressions; the existing
``test_service_client_sessions_offer_no_work.py`` is already over its
300-line design target.
"""

from __future__ import annotations


def _build_schedule(steps):
    from yoke_core.domain.scheduler_types import SchedulerResult, SMLState

    return SchedulerResult(
        project_scope=["yoke"],
        sml_state=SMLState(coherent=True),
        ranked_steps=steps,
        selected_step=steps[0] if steps else None,
    )


def _make_step(item_id, rank, claim_state, next_step_value="advance"):
    from yoke_core.domain.scheduler_types import (
        ClaimState,
        NextStep,
        ScheduledStep,
    )

    _next_step_map = {
        "advance": NextStep.ADVANCE,
        "refine": NextStep.REFINE,
        "polish": NextStep.POLISH,
        "usher": NextStep.USHER,
    }
    _claim_state_map = {
        "unclaimed": ClaimState.UNCLAIMED,
        "claimed_by_stale": ClaimState.CLAIMED_BY_STALE,
        "claimed_by_self": ClaimState.CLAIMED_BY_SELF,
        "claimed_by_other_live": ClaimState.CLAIMED_BY_OTHER_LIVE,
    }
    return ScheduledStep(
        item_id=item_id,
        item_type="issue",
        status="refined-idea",
        title=f"{item_id} title",
        priority="high",
        next_step=_next_step_map[next_step_value],
        rank=rank,
        claim_state=_claim_state_map[claim_state],
    )


class TestFrontierPromotion:
    """Direct unit tests for build_frontier_state_from_schedule promotion."""

    def test_top_step_in_skip_memory_promotes_next_surviving_ranked_step(self):
        """AC-1, AC-5(a): top pick filtered promotes next surviving step.

        Two ranked steps. Scheduler selects rank-0 YOK-A. With YOK-A in
        skip-memory the builder must promote YOK-B and populate the
        scheduler_context from YOK-B's fields.
        """
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="unclaimed"),
        ]
        schedule = _build_schedule(steps)

        baseline = build_frontier_state_from_schedule(schedule)
        assert baseline.selected_item == "YOK-A"

        filtered = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )
        assert filtered.runnable_items == ["YOK-B"]
        assert filtered.selected_item == "YOK-B"
        assert filtered.scheduler_context["next_step"] == "advance"
        assert filtered.scheduler_context["item_type"] == "issue"
        assert filtered.scheduler_context["rank"] == 1

    def test_all_ranked_steps_filtered_keeps_selected_none(self):
        """AC-2, AC-5(b), AC-7: when every step is filtered, fall back to no-work.

        YOK-A is in skip-memory. YOK-B is held by a live claim
        (CLAIMED_BY_OTHER_LIVE, not assignable). No surviving entry,
        so selected stays None and scheduler_context stays {}.
        """
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="claimed_by_other_live"),
        ]
        schedule = _build_schedule(steps)

        filtered = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )
        # YOK-B is not assignable, so runnable_items is empty too.
        assert filtered.runnable_items == []
        assert filtered.selected_item is None
        assert filtered.scheduler_context == {}

    def test_runnable_items_projection_unchanged_by_promotion(self):
        """AC-3: runnable_items contents and order match pre-fix behavior."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="unclaimed"),
            _make_step("YOK-C", rank=2, claim_state="claimed_by_stale"),
        ]
        schedule = _build_schedule(steps)

        # Without skip memory: all three are assignable; runnable matches rank order.
        baseline = build_frontier_state_from_schedule(schedule)
        assert baseline.runnable_items == ["YOK-A", "YOK-B", "YOK-C"]

        # With YOK-A skipped: runnable is the rank-ordered survivors,
        # selected is promoted to YOK-B.
        filtered = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )
        assert filtered.runnable_items == ["YOK-B", "YOK-C"]
        assert filtered.selected_item == "YOK-B"


class TestChargeDispatchPath:
    """Integration: promoted scheduler_context flows through decide_charge_action.

    AC-5(c) / AC-6: when the failure shape from the 2026-05-10 evidence is
    reconstructed at the frontier-state layer, the decision engine returns
    a charge action with context.scheduler.next_step populated so the
    /yoke do charge dispatch contract is satisfied.
    """

    def test_charge_action_carries_promoted_scheduler_context(self):
        from yoke_core.domain.session_contract import (
            ActionKind,
            SessionOffer,
        )
        from yoke_core.domain.session_decision_charge import decide_charge_action
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        # Two assignable ranked steps, scheduler picks rank-0 YOK-A, but
        # YOK-A is in chain_skip_memory (e.g. live-claim conflict resolved
        # by the offer revalidation path). YOK-B must be promoted.
        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="unclaimed"),
        ]
        schedule = _build_schedule(steps)
        frontier = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )

        offer = SessionOffer(
            session_id="test-session",
            executor="claude-code",
            provider="anthropic",
            model="claude-opus-4-7",
            workspace="/tmp/yoke-test",
            execution_lane="primary",
        )
        action = decide_charge_action(
            offer=offer,
            frontier=frontier,
            correlation="test-corr",
            lane_allowed_paths=None,
        )

        assert action is not None
        assert action.action == ActionKind.CHARGE
        assert action.context["selected_item"] == "YOK-B"
        # The canonical dispatch contract: charge context carries the
        # scheduler block with next_step populated.
        assert "scheduler" in action.context
        assert action.context["scheduler"]["next_step"] == "advance"


class TestSchedulerContextCarriesSelectedItem:
    """AC-4, AC-5: scheduler_context["selected_item"] must be populated
    for every selected step (baseline and promoted), so the
    ``decide_charge_action`` mismatch guard at
    ``session_decision_charge.py:76-91`` is no longer silently disabled
    and ``SessionOfferInvariantFailed`` carries non-null
    ``schedule_selected_item``."""

    def test_baseline_selected_step_populates_scheduler_context_selected_item(self):
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="unclaimed"),
        ]
        schedule = _build_schedule(steps)

        baseline = build_frontier_state_from_schedule(schedule)
        assert baseline.selected_item == "YOK-A"
        assert baseline.scheduler_context["selected_item"] == "YOK-A"
        # Both frontier-level and scheduler-block selected_item agree.
        assert (
            baseline.scheduler_context["selected_item"]
            == baseline.selected_item
        )

    def test_promoted_selected_step_populates_scheduler_context_selected_item(self):
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            _make_step("YOK-A", rank=0, claim_state="unclaimed"),
            _make_step("YOK-B", rank=1, claim_state="unclaimed"),
        ]
        schedule = _build_schedule(steps)

        filtered = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )
        assert filtered.selected_item == "YOK-B"
        assert filtered.scheduler_context["selected_item"] == "YOK-B"

    def test_scheduler_context_empty_when_no_selected_step(self):
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        # All steps filtered or non-assignable -> selected_step None ->
        # scheduler_context is empty dict, no selected_item key.
        steps = [
            _make_step("YOK-A", rank=0, claim_state="claimed_by_other_live"),
        ]
        schedule = _build_schedule(steps)
        # Schedule.selected_step is set by _build_schedule above, but
        # the builder will drop it via the skip-memory branch only if
        # the item is also in skip-memory. Use that path:
        result = build_frontier_state_from_schedule(
            schedule, skip_memory_item_ids={"YOK-A"},
        )
        assert result.selected_item is None
        assert result.scheduler_context == {}

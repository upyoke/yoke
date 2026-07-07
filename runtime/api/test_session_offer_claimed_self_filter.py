"""Regression for retry-time ``claimed_by_self`` offer filtering.

Telemetry anchors: ``1654441`` skipped the initial item after a live
claim appeared; ``1655486`` recorded the retry claim; ``1655499`` showed
the recomputed selected step as ``claimed_by_self``; ``1655840`` captured
the mismatch guard refusing a stale ``selected_item`` / new-claim pair.
"""

from __future__ import annotations

from yoke_core.domain.scheduler_types import (
    ClaimState,
    NextStep,
    ScheduledStep,
    SchedulerResult,
    is_assignable_claim_state,
)
from yoke_core.domain.sessions_queries_base import (
    _filter_schedule_for_offer,
)


def _step(
    *,
    item_id: str,
    rank: int,
    claim_state: ClaimState,
) -> ScheduledStep:
    return ScheduledStep(
        item_id=item_id,
        item_type="issue",
        status="reviewed-implementation",
        title=f"Item {item_id}",
        priority="high",
        next_step=NextStep.POLISH,
        rank=rank,
        claim_state=claim_state,
    )


def _run(schedule: SchedulerResult) -> SchedulerResult:
    # Permissive lane/path: the bug is on the assignability axis.
    return _filter_schedule_for_offer(
        schedule,
        execution_lane="DARIUS",
        supported_paths=None,
        lane_allowed_paths=None,
    )


class TestFilterPreservesClaimedBySelf:
    """AC-1, AC-2, AC-5: self-held steps stay selected."""

    def test_claimed_by_self_selected_step_survives_filter(self):
        self_held = _step(
            item_id="YOK-A", rank=4,
            claim_state=ClaimState.CLAIMED_BY_SELF,
        )
        later = _step(item_id="YOK-B", rank=5, claim_state=ClaimState.UNCLAIMED)
        schedule = SchedulerResult(
            selected_step=self_held,
            ranked_steps=[self_held, later],
        )

        filtered = _run(schedule)

        assert filtered.selected_step is not None
        assert filtered.selected_step.item_id == "YOK-A"
        assert filtered.selected_step.claim_state == ClaimState.CLAIMED_BY_SELF

    def test_claimed_by_other_live_is_dropped_from_selected(self):
        live = _step(
            item_id="YOK-A", rank=1,
            claim_state=ClaimState.CLAIMED_BY_OTHER_LIVE,
        )
        unclaimed = _step(item_id="YOK-B", rank=2, claim_state=ClaimState.UNCLAIMED)
        schedule = SchedulerResult(selected_step=live, ranked_steps=[live, unclaimed])

        filtered = _run(schedule)

        assert filtered.selected_step is not None
        assert filtered.selected_step.item_id == "YOK-B"


class TestRetryRecomputeMirrorsIncident:
    """AC-3, AC-4: retry recompute keeps the new claim selected."""

    def test_recomputed_selected_matches_new_claim_after_retry(self):
        live_held = _step(
            item_id="YOK-INITIAL",
            rank=1,
            claim_state=ClaimState.CLAIMED_BY_OTHER_LIVE,
        )
        new_claim = _step(
            item_id="YOK-NEW-CLAIM",
            rank=4,
            claim_state=ClaimState.CLAIMED_BY_SELF,
        )
        later = _step(
            item_id="YOK-NEXT-UNCLAIMED",
            rank=5,
            claim_state=ClaimState.UNCLAIMED,
        )
        schedule = SchedulerResult(
            selected_step=new_claim,
            ranked_steps=[live_held, new_claim, later],
        )

        filtered = _run(schedule)

        assert filtered.selected_step is not None
        assert filtered.selected_step.item_id == "YOK-NEW-CLAIM"
        assert [s.item_id for s in filtered.ranked_steps] == [
            "YOK-INITIAL",
            "YOK-NEW-CLAIM",
            "YOK-NEXT-UNCLAIMED",
        ]

    def test_charge_context_matches_new_claim_after_filter(self):
        from yoke_core.domain.session_contract import ActionKind, SessionOffer
        from yoke_core.domain.session_decision_charge import decide_charge_action
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )
        from yoke_core.api.service_client_sessions_offer_helpers import (
            validate_charge_claim_invariant,
        )

        new_claim = _step(
            item_id="YOK-1723", rank=4,
            claim_state=ClaimState.CLAIMED_BY_SELF,
        )
        later = _step(
            item_id="YOK-1724", rank=5,
            claim_state=ClaimState.UNCLAIMED,
        )
        filtered = _run(SchedulerResult(
            selected_step=new_claim,
            ranked_steps=[new_claim, later],
        ))
        frontier = build_frontier_state_from_schedule(filtered)
        offer = SessionOffer(
            session_id="incident-session",
            executor="codex",
            provider="openai",
            model="gpt-5.5",
            workspace="/tmp/yoke",
            execution_lane="ALTMAN",
        )

        action = decide_charge_action(
            offer=offer,
            frontier=frontier,
            correlation="incident-session",
            lane_allowed_paths=None,
        )

        assert action is not None
        assert action.action == ActionKind.CHARGE
        assert action.context["selected_item"] == "YOK-1723"
        ok, err = validate_charge_claim_invariant(action, {"item_id": 1723})
        assert ok is True, err


class TestFilterDelegatesToSharedHelper:
    """AC-6: filter selection matches the shared helper."""

    def test_filter_parity_with_shared_helper(self):
        for state in ClaimState:
            step = _step(item_id="YOK-X", rank=1, claim_state=state)
            schedule = SchedulerResult(selected_step=step, ranked_steps=[step])
            filtered = _run(schedule)
            if is_assignable_claim_state(state):
                assert filtered.selected_step is not None
                assert filtered.selected_step.claim_state == state
            else:
                assert filtered.selected_step is None

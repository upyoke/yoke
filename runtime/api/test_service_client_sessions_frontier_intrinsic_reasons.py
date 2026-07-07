"""Intrinsic-reasons channel tests for build_frontier_state_from_schedule.

Sibling to ``test_service_client_sessions_frontier_promote.py``. Covers
``FrontierState.intrinsic_blocked_reasons`` adapter parity (intrinsic-only,
gates-only, both), per-class authoring (idea-incomplete, operator-set block,
routed-ownership defense), fallback parity when both channels are empty,
and the decision-engine escalate-branch copy.

Extracted into its own module so the existing promote-test file stays under
its design-target line count.
"""

from __future__ import annotations


def _make_blocked_step(
    item_id,
    *,
    status="idea",
    blocked_reasons=None,
    gate_evaluations=None,
):
    from yoke_core.domain.scheduler_types import (
        ClaimState,
        NextStep,
        ScheduledStep,
    )

    return ScheduledStep(
        item_id=item_id,
        item_type="issue",
        status=status,
        title=f"{item_id} title",
        priority="medium",
        next_step=NextStep.REFINE,
        rank=0,
        claim_state=ClaimState.UNCLAIMED,
        gate_evaluations=gate_evaluations or [],
        blocked_reasons=list(blocked_reasons or []),
    )


def _make_gate_eval(blocking_item, *, satisfied=False, gate_point="activation"):
    from yoke_core.domain.scheduler_types import GateEvaluation

    return GateEvaluation(
        blocking_item=blocking_item,
        relation="blocker",
        gate_point=gate_point,
        satisfaction="status:done",
        satisfied=satisfied,
        reason=f"blocked by {blocking_item}",
        rationale="dependency rationale",
    )


def _schedule_with_blocked(blocked_steps, *, runnable_steps=None):
    from yoke_core.domain.scheduler_types import SchedulerResult, SMLState

    return SchedulerResult(
        project_scope=["yoke"],
        sml_state=SMLState(coherent=True),
        ranked_steps=list(runnable_steps or []),
        selected_step=(runnable_steps or [None])[0],
        blocked_steps=list(blocked_steps),
    )


class TestIntrinsicReasonsAdapter:
    """Adapter parity tests for FrontierState.intrinsic_blocked_reasons."""

    def test_intrinsic_only_populates_intrinsic_channel_and_leaves_gates_none(self):
        """AC-2: intrinsic-only blockage -> intrinsic_blocked_reasons populated, blocked_details=None."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        bs = _make_blocked_step(
            "YOK-IDEA",
            status="idea",
            blocked_reasons=[
                "idea-incomplete: idea body is title-only (no spec content yet). "
                "Either /yoke idea is still in flight or a prior draft session "
                "crashed before persisting the spec. Run /yoke doctor to inspect."
            ],
        )
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.blocked_details is None
        assert result.intrinsic_blocked_reasons is not None
        assert len(result.intrinsic_blocked_reasons) == 1
        entry = result.intrinsic_blocked_reasons[0]
        assert entry["item_id"] == "YOK-IDEA"
        assert entry["status"] == "idea"
        assert entry["reasons"] == bs.blocked_reasons

    def test_gates_only_populates_blocked_details_and_leaves_intrinsic_none(self):
        """AC-2: gate-only blockage -> blocked_details populated, intrinsic_blocked_reasons=None."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        bs = _make_blocked_step(
            "YOK-GATED",
            status="refined-idea",
            blocked_reasons=[],
            gate_evaluations=[_make_gate_eval("YOK-UPSTREAM")],
        )
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.blocked_details is not None
        assert len(result.blocked_details) == 1
        assert result.blocked_details[0]["item_id"] == "YOK-GATED"
        assert result.blocked_details[0]["blocking_item"] == "YOK-UPSTREAM"
        assert result.intrinsic_blocked_reasons is None

    def test_both_channels_coexist_when_step_carries_intrinsic_and_gate(self):
        """AC-7: both channels populate when a step has both intrinsic reasons and unsatisfied gates."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        bs = _make_blocked_step(
            "YOK-MIXED",
            status="refined-idea",
            blocked_reasons=["Blocked by operator: clarifying ownership question"],
            gate_evaluations=[_make_gate_eval("YOK-UPSTREAM")],
        )
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.blocked_details is not None
        assert len(result.blocked_details) == 1
        assert result.blocked_details[0]["item_id"] == "YOK-MIXED"
        assert result.intrinsic_blocked_reasons is not None
        assert len(result.intrinsic_blocked_reasons) == 1
        intrinsic = result.intrinsic_blocked_reasons[0]
        assert intrinsic["item_id"] == "YOK-MIXED"
        assert intrinsic["status"] == "refined-idea"
        assert any("operator" in r.lower() for r in intrinsic["reasons"])

    def test_idea_incomplete_reason_string_round_trips_verbatim(self):
        """AC-5: idea-incomplete reason from frontier_compute._IDEA_INCOMPLETE_REASON arrives verbatim."""
        from yoke_core.domain.idea_body_completeness import INCOMPLETE_REASON as _IDEA_INCOMPLETE_REASON
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        reason_str = (
            f"{_IDEA_INCOMPLETE_REASON}: idea body is title-only "
            "(no spec content yet). Either /yoke idea is still in flight "
            "or a prior draft session crashed before persisting the spec. "
            "Run /yoke doctor to inspect."
        )
        bs = _make_blocked_step("YOK-IDEA2", status="idea", blocked_reasons=[reason_str])
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.intrinsic_blocked_reasons is not None
        assert result.intrinsic_blocked_reasons[0]["reasons"] == [reason_str]
        assert _IDEA_INCOMPLETE_REASON in result.intrinsic_blocked_reasons[0]["reasons"][0]

    def test_operator_block_rendering_round_trips(self):
        """AC-6: operator-set block rendering ``Blocked by operator: <reason>`` arrives verbatim."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        rendered = "Blocked by operator: needs Alice's review before unblocking"
        bs = _make_blocked_step("YOK-OP", status="refined-idea", blocked_reasons=[rendered])
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.intrinsic_blocked_reasons is not None
        assert result.intrinsic_blocked_reasons[0]["reasons"] == [rendered]

    def test_routed_ownership_defense_reason_round_trips(self):
        """AC-11: routed-ownership defense reason surfaces through intrinsic_blocked_reasons."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        routed_reason = (
            "Excluded by routed-ownership defense: item is being routed to another "
            "harness or session."
        )
        bs = _make_blocked_step("YOK-ROUTED", status="implementing", blocked_reasons=[routed_reason])
        schedule = _schedule_with_blocked([bs])

        result = build_frontier_state_from_schedule(schedule)

        assert result.intrinsic_blocked_reasons is not None
        assert result.intrinsic_blocked_reasons[0]["reasons"] == [routed_reason]

    def test_both_channels_none_when_blocked_steps_empty(self):
        """AC-10 supporting case: empty blocked_steps leaves both channels None."""
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        schedule = _schedule_with_blocked([])

        result = build_frontier_state_from_schedule(schedule)

        assert result.blocked_details is None
        assert result.intrinsic_blocked_reasons is None


class TestDecisionEngineEscalateCopy:
    """The escalate branch copies intrinsic_blocked_reasons into NextAction.context."""

    def _build_offer(self):
        from yoke_core.domain.session_contract import SessionOffer

        return SessionOffer(
            session_id="test-session",
            executor="claude-desktop",
            provider="anthropic",
            model="claude-opus-4-7",
            workspace="/Users/dev/yoke",
            execution_lane="DARIUS",
            step=1,
            supported_paths=["refine", "advance", "polish", "usher"],
        )

    def test_escalate_branch_copies_intrinsic_blocked_reasons(self):
        """AC-3: when intrinsic_blocked_reasons is non-empty, the escalate context carries it."""
        from yoke_core.domain.session_contract import FrontierState
        from yoke_core.domain.session_decision import decide_next_action

        offer = self._build_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-IDEA"],
            exceptional_items=[],
            blocked_details=None,
            intrinsic_blocked_reasons=[
                {"item_id": "YOK-IDEA", "status": "idea", "reasons": ["idea-incomplete: ..."]},
            ],
            sml_coherent=True,
        )

        action = decide_next_action(offer, frontier)

        assert action.action.value == "escalate"
        assert action.context.get("intrinsic_blocked_reasons") == frontier.intrinsic_blocked_reasons

    def test_escalate_branch_omits_intrinsic_key_when_field_is_none(self):
        """AC-10 supporting: when intrinsic_blocked_reasons is None, escalate ctx does not set the key."""
        from yoke_core.domain.session_contract import FrontierState
        from yoke_core.domain.session_decision import decide_next_action

        offer = self._build_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-GATED"],
            exceptional_items=[],
            blocked_details=[{
                "item_id": "YOK-GATED",
                "blocking_item": "YOK-UPSTREAM",
                "gate_point": "activation",
                "satisfaction": "status:done",
                "rationale": "edge rationale",
                "reason": "blocked by YOK-UPSTREAM",
            }],
            intrinsic_blocked_reasons=None,
            sml_coherent=True,
        )

        action = decide_next_action(offer, frontier)

        assert action.action.value == "escalate"
        assert "intrinsic_blocked_reasons" not in action.context
        assert "blocked_details" in action.context

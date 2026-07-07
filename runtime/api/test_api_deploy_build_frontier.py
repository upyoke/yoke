"""``_build_frontier_state`` unit tests."""

from __future__ import annotations

from yoke_core.api.main import _build_frontier_state


class TestBuildFrontierStateDriftReview:
    """_build_frontier_state propagates drift_review."""

    def test_drift_review_passed_through(self):
        from yoke_core.domain.scheduler import SchedulerResult, SMLState
        schedule = SchedulerResult(sml_state=SMLState(coherent=True))
        drift = {"classification": "frontier_only", "summary": "test"}
        frontier = _build_frontier_state(schedule, drift_review_dict=drift)
        assert frontier.drift_review == drift

    def test_no_drift_review_default(self):
        from yoke_core.domain.scheduler import SchedulerResult, SMLState
        schedule = SchedulerResult(sml_state=SMLState(coherent=True))
        frontier = _build_frontier_state(schedule)
        assert frontier.drift_review is None

    def test_last_completed_step_passed_through(self):
        from yoke_core.domain.scheduler import SchedulerResult, SMLState
        schedule = SchedulerResult(sml_state=SMLState(coherent=True))
        checkpoint = {"action": "resume", "item_id": "YOK-10"}
        frontier = _build_frontier_state(schedule, last_completed_step=checkpoint)
        assert frontier.last_completed_step == checkpoint

    def test_scheduler_context_preserves_next_step(self):
        from yoke_core.domain.scheduler import (
            NextStep,
            ScheduledStep,
            SchedulerResult,
            SMLState,
        )

        step = ScheduledStep(
            item_id=f"YOK-{1000}",
            item_type="issue",
            status="idea",
            title="Needs refinement",
            priority="medium",
            next_step=NextStep.REFINE,
        )
        schedule = SchedulerResult(
            sml_state=SMLState(coherent=True),
            selected_step=step,
            ranked_steps=[step],
        )
        frontier = _build_frontier_state(schedule)

        assert frontier.scheduler_context["next_step"] == "refine"

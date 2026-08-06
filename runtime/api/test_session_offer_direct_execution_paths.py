"""Offer-time compatibility for the direct-execution next_steps.

Dash and Blitz items are routable scheduler next_steps. If the shared
capability registry or the default lane policy omits their paths, the offer
filter drops every such candidate before the decision engine runs, and a
session with only Dash work on the frontier reports "no work" instead of
dispatching.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.harness_capability_registry import shared_downstream_paths
from yoke_core.domain.project_session_routing_defaults import (
    _SESSION_ROUTING_DEFAULTS,
)
from yoke_core.domain.scheduler_types import (
    ClaimState,
    NextStep,
    ScheduledStep,
    SchedulerResult,
)
from yoke_core.domain.sessions_queries_base import _filter_schedule_for_offer

DIRECT_EXECUTION_STEPS = (NextStep.DASH, NextStep.BLITZ)


def _step(next_step: NextStep) -> ScheduledStep:
    return ScheduledStep(
        item_id=101,
        workflow_id=next_step.value,
        workflow_version_id=1,
        workflow_version=1,
        status="idea",
        title=f"Item routed to {next_step.value}",
        priority="high",
        next_step=next_step,
        rank=0,
        claim_state=ClaimState.UNCLAIMED,
    )


@pytest.mark.parametrize("next_step", DIRECT_EXECUTION_STEPS)
def test_step_survives_registry_derived_supported_paths(next_step):
    step = _step(next_step)
    schedule = SchedulerResult(selected_step=step, ranked_steps=[step])

    filtered = _filter_schedule_for_offer(
        schedule,
        execution_lane="DARIUS",
        supported_paths=shared_downstream_paths(),
        lane_allowed_paths=None,
    )

    assert filtered.selected_step is not None
    assert filtered.lane_filtered_count == 0


@pytest.mark.parametrize("next_step", DIRECT_EXECUTION_STEPS)
def test_step_survives_default_lane_policy(next_step):
    step = _step(next_step)
    schedule = SchedulerResult(selected_step=step, ranked_steps=[step])
    lane_paths = _SESSION_ROUTING_DEFAULTS["lane_paths"]

    filtered = _filter_schedule_for_offer(
        schedule,
        execution_lane="DARIUS",
        supported_paths=shared_downstream_paths(),
        lane_allowed_paths=lane_paths,
    )

    assert filtered.selected_step is not None
    assert filtered.lane_filtered_count == 0

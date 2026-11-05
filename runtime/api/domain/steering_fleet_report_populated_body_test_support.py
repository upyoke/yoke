# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import dataclasses

from runtime.api.steering_fleet_test_helpers import (
    IDLE_SECONDS,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STAFFING_SECONDS,
    SURFACE,
)

from yoke_core.domain.delivery_landing_custody import HELD, REMERGED

from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport

from yoke_core.domain.steering_fleet_report_render import report_body


def _populated_report():
    """One report with every section non-empty, built without touching a DB."""
    from yoke_core.domain.steering_fleet_report_available import FrontierEntry
    from yoke_core.domain.steering_fleet_report_capacity import (
        SessionCount,
        SurfaceReadiness,
    )
    from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait
    from yoke_core.domain.steering_fleet_report_detectors import (
        UnregisteredLaunch,
    )
    from yoke_core.domain.steering_fleet_report_landed_gate import (
        AWAITING_RELEASE,
        LandedGate,
    )
    from yoke_core.domain.steering_fleet_report_landed_open import LandedItem
    from yoke_core.domain.steering_fleet_report_delivery_states import (
        NEVER_ATTEMPTED,
    )
    from yoke_core.domain.steering_fleet_report_undelivered import (
        UndeliveredMessages,
    )

    quiet = ClaimHolder(
        session_id="holder-session",
        item_id=3,
        public_ref="YOK-3",
        mode="dash",
        parked=False,
        last_activity_at=LONG_AGO,
        idle_seconds=3 * 3600,
    )
    working = dataclasses.replace(
        quiet,
        session_id="working-session",
        item_id=5,
        public_ref="YOK-5",
        idle_seconds=120,
    )
    return FleetReport(
        project_id=PROJECT_ID,
        composed_at=NOW,
        staffing_after_seconds=STAFFING_SECONDS,
        idle_after_seconds=IDLE_SECONDS,
        available=(
            FrontierEntry(
                item_id=1,
                public_ref="YOK-1",
                title="Long-unpicked work",
                next_step="implement",
                rank=1,
                pickable_since=LONG_AGO,
                was_owned=False,
            ),
            FrontierEntry(
                item_id=2,
                public_ref="YOK-2",
                title="Just released work",
                next_step="implement",
                rank=2,
                pickable_since=JUST_NOW,
                was_owned=True,
            ),
        ),
        holders=(quiet, working),
        idle=(quiet,),
        undelivered=(
            UndeliveredMessages(
                session_id="undelivered-session",
                delivery_state=NEVER_ATTEMPTED,
                envelope_count=2,
                oldest_seconds=2400,
            ),
        ),
        unregistered_launches=(
            UnregisteredLaunch(
                launch_id="launch-1",
                surface=SURFACE,
                machine_id="machine-1",
                state="outcome_unknown",
                overdue_seconds=0,
                result_code="identity_parse_failed",
                native_launch_pid=4242,
                native_launch_phase="spawn_completed_after_bound",
                spawn_duration_ms=103_000,
            ),
            UnregisteredLaunch(
                launch_id="launch-model-rejected",
                surface="claude-cli",
                machine_id="machine-1",
                state="failed",
                overdue_seconds=0,
                result_code="model_combo_unsupported",
                detail="model does not support effort max",
            ),
        ),
        landed_open=(
            LandedItem(
                item_id=4,
                public_ref="YOK-4",
                status="reviewing-implementation",
                landed_at=LONG_AGO,
                landed_seconds=3 * 3600,
                holder_session_id="holder-session",
                delivery_gate=LandedGate(AWAITING_RELEASE, flow="hosted-release"),
            ),
        ),
        dead_waits=(
            DeadWait(
                session_id="holder-session",
                item_id=3,
                public_ref="YOK-3",
                asked_seconds=7800,
                answerer_session_id="gone-session",
                reason="answerer session has ended",
            ),
        ),
        suspected_orphaned_waiters=(quiet,),
        launchable=(SurfaceReadiness(machine_id="machine-1", surface=SURFACE),),
        session_counts=(
            SessionCount(
                machine_id="machine-1",
                surface=SURFACE,
                count=2,
                requested_model="gpt-5.6-sol",
                requested_reasoning_effort="high",
                requested_context_window_tokens=None,
                model="gpt-5.6-sol",
                reasoning_effort="high",
                context_window_tokens=None,
            ),
        ),
        origin_counts=(("operator", 1), ("steering", 1)),
    )

"""The rendered body of a report whose every section has something to say.

These build the report in memory rather than through a database, because
what is under test is the render: which sections appear, in what order,
and which marks each row carries. The length assertion is load-bearing —
this body is appended to every message a steering session receives.
"""

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
        LandedItem,
        UnregisteredLaunch,
    )
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
                next_step="advance",
                rank=1,
                pickable_since=LONG_AGO,
                was_owned=False,
            ),
            FrontierEntry(
                item_id=2,
                public_ref="YOK-2",
                title="Just released work",
                next_step="advance",
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


def test_every_section_renders_in_the_order_a_steerer_reads_them():
    body = report_body(_populated_report())

    order = [
        "available —",
        "idle holders —",
        "suspected orphaned waiter —",
        "undelivered messages —",
        "unregistered launches —",
        "landed without close-out —",
        "dead waits —",
        "live item claims",
        "launchable machine/surface pairs",
    ]
    positions = [body.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_a_row_carries_the_marks_that_decide_what_to_do_with_it():
    body = report_body(_populated_report())

    overdue_row = next(line for line in body.splitlines() if "YOK-1" in line)
    fresh_row = next(line for line in body.splitlines() if "YOK-2" in line)
    landed_row = next(line for line in body.splitlines() if "YOK-4" in line)
    assert overdue_row.lstrip().startswith("!")
    assert " new " in overdue_row
    assert not fresh_row.lstrip().startswith("!")
    assert " stopped " in fresh_row
    assert "still reviewing-implementation" in landed_row
    assert "do not wait on status" in landed_row
    assert "yoke merge item YOK-4" in landed_row
    # Who can run close-out is on the row, because with a live holder the
    # recovery is a message to that session and with none it is staffing.
    assert "holder-session" in landed_row
    launch_row = next(line for line in body.splitlines() if "launch-1" in line)
    assert "identity parse failed" in launch_row
    assert "instruction not delivered" in launch_row
    assert "native pid 4242 spawn_completed_after_bound" in launch_row
    assert "spawn 103.0s" in launch_row
    assert "reconcile launch-1 --observed-native-id ID" in launch_row
    rejected = next(
        line for line in body.splitlines() if "launch-model-rejected" in line
    )
    assert "model does not support effort max" in rejected
    assert "choose a supported model, effort, and context combination" in rejected
    waiter_row = next(line for line in body.splitlines() if "wake `yoke say" in line)
    assert "YOK-3" in waiter_row
    assert "session holder-session" in waiter_row
    assert "yoke say --item YOK-3 --stdin" in waiter_row


def test_a_landed_item_nobody_holds_says_so_instead_of_naming_a_session():
    """With no holder the recovery is staffing, so the row must not read empty."""
    report = _populated_report()
    unheld = dataclasses.replace(report.landed_open[0], holder_session_id=None)

    body = report_body(dataclasses.replace(report, landed_open=(unheld,)))

    landed_row = next(line for line in body.splitlines() if "YOK-4" in line)
    assert "no live holder" in landed_row


def test_the_populated_report_stays_short_enough_to_ride_every_message():
    """It is appended to every message a steering session gets, forever."""
    body = report_body(_populated_report())

    assert "origin operator 1 · steering 1" in body
    assert len(body.splitlines()) <= 31


def test_full_sections_are_reported_as_actionable():
    assert _populated_report().actionable is True

"""What the steerer actually reads: section order, row marks, and silence."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    IDLE_SECONDS,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STAFFING_SECONDS,
    SURFACE,
    WORKER_SESSION,
    compose as _compose,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_report import ClaimHolder, FleetReport
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def test_the_body_leads_with_the_work_a_steerer_can_staff(steering_scope):
    """Available work above the alarms: the ordering the old report inverted."""
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )

    body = report_body(_compose(steering_scope))

    assert body.startswith("=== BEGIN YOKE FLEET REPORT ===")
    assert body.index("available") < body.index("idle holders")
    assert body.index("available") < body.index("live item claims")
    assert "not instructions" in body
    assert "YOK-1" in body
    assert "launch balance  machine-1" in body
    assert "codex-cli 2" in body
    assert "try to maximize balance with each new session launch" in body


def test_launch_balance_omits_a_surface_that_cannot_accept_a_launch(steering_scope):
    seed_session(
        steering_scope,
        "desktop-worker",
        executor="claude-code",
        executor_surface="claude-desktop",
    )
    steering_scope.commit()

    body = report_body(_compose(steering_scope))

    assert "claude-desktop" not in body
    assert "codex-cli 2" in body


def test_launch_balance_shows_zero_only_for_an_empty_launchable_surface(
    steering_scope,
):
    steering_scope.execute(
        "UPDATE session_relays SET surface_versions = %s WHERE relay_id = 'relay-1'",
        (json.dumps({SURFACE: "0.148.0a15", "claude-cli": "2.1.238"}),),
    )
    steering_scope.commit()

    body = report_body(_compose(steering_scope))

    assert "claude-cli 0" in body
    assert "codex-cli 2" in body
    assert "claude-desktop" not in body


def test_ended_and_terminated_sessions_do_not_count_toward_launch_balance(
    steering_scope,
):
    seed_session(steering_scope, "ended-worker", ended_at=JUST_NOW)
    seed_session(steering_scope, "terminated-worker", terminated_at=JUST_NOW)
    steering_scope.commit()

    body = report_body(_compose(steering_scope))

    assert "codex-cli 2" in body
    assert "codex-cli 3" not in body
    assert "codex-cli 4" not in body


def test_the_available_heading_says_what_the_section_holds(steering_scope):
    """The heading that read 'not waiting' over rows waiting 30h is the bug."""
    body = report_body(_compose(steering_scope))

    heading = next(line for line in body.splitlines() if line.startswith("available"))
    assert "runnable and unclaimed" in heading
    assert "not waiting" not in body


def test_a_quiet_detector_renders_nothing_at_all(steering_scope):
    """Every section is a cost paid on every delivery; empty ones cost nothing."""
    body = report_body(_compose(steering_scope))

    for absent in (
        "starved delivery",
        "unregistered launches",
        "landed without close-out",
        "dead waits",
    ):
        assert absent not in body
    assert ": none" not in body.replace("launchable machine/surface pairs: none", "")


def _populated_report():
    """One report with every section non-empty, built without touching a DB."""
    from yoke_core.domain.steering_fleet_report_available import FrontierEntry
    from yoke_core.domain.steering_fleet_report_capacity import SurfaceReadiness
    from yoke_core.domain.steering_fleet_report_dead_waits import DeadWait
    from yoke_core.domain.steering_fleet_report_detectors import (
        LandedItem,
        StarvedDelivery,
        UnregisteredLaunch,
    )

    quiet = ClaimHolder(
        session_id="holder-session",
        item_id=3,
        item_ref="YOK-3",
        mode="dash",
        parked=False,
        last_activity_at=LONG_AGO,
        idle_seconds=3 * 3600,
    )
    return FleetReport(
        project_id=PROJECT_ID,
        composed_at=NOW,
        staffing_after_seconds=STAFFING_SECONDS,
        idle_after_seconds=IDLE_SECONDS,
        available=(
            FrontierEntry(
                item_id=1,
                item_ref="YOK-1",
                title="Long-unpicked work",
                next_step="advance",
                rank=1,
                pickable_since=LONG_AGO,
                was_owned=False,
            ),
            FrontierEntry(
                item_id=2,
                item_ref="YOK-2",
                title="Just released work",
                next_step="advance",
                rank=2,
                pickable_since=JUST_NOW,
                was_owned=True,
            ),
        ),
        holders=(quiet,),
        idle=(quiet,),
        starved=(
            StarvedDelivery(
                session_id="starved-session", envelope_count=2, oldest_seconds=2400
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
            ),
        ),
        landed_open=(
            LandedItem(
                item_id=4,
                item_ref="YOK-4",
                status="reviewing-implementation",
                landed_at=LONG_AGO,
                landed_seconds=3 * 3600,
            ),
        ),
        dead_waits=(
            DeadWait(
                session_id="holder-session",
                item_id=3,
                item_ref="YOK-3",
                asked_seconds=7800,
                answerer_session_id="gone-session",
                reason="answerer session has ended",
            ),
        ),
        launchable=(SurfaceReadiness(machine_id="machine-1", surface=SURFACE),),
        session_counts=(("machine-1", SURFACE, 2),),
    )


def test_every_section_renders_in_the_order_a_steerer_reads_them():
    body = report_body(_populated_report())

    order = [
        "available —",
        "idle holders —",
        "starved delivery —",
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
    launch_row = next(line for line in body.splitlines() if "launch-1" in line)
    assert "identity parse failed" in launch_row
    assert "instruction not delivered" in launch_row
    assert "reconcile launch-1 --observed-native-id ID" in launch_row


def test_the_populated_report_stays_short_enough_to_ride_every_message():
    """It is appended to every message a steering session gets, forever."""
    body = report_body(_populated_report())

    assert len(body.splitlines()) <= 30


def test_full_sections_are_reported_as_actionable():
    assert _populated_report().actionable is True

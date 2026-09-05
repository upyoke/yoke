"""What the steerer actually reads: section order, row marks, and silence."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    SURFACE,
    WORKER_SESSION,
    compose as _compose,
    seed_session,
    seed_steering_scope,
)
from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
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
    assert "not instructions" in body
    assert "YOK-1" in body
    assert "launch balance  machine-1" in body
    assert "codex-cli 2" in body
    assert "origin operator 0 · steering 0" in body
    assert "send the rest to the surface with the most headroom and run it down" in body


def test_process_gone_holder_is_actionable_without_offering_a_wake(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    steering_scope.execute(
        "UPDATE harness_sessions SET mode='parked', "
        "native_process_gone_at='2026-08-26T12:01:00Z', "
        "native_process_gone_evidence='{}' WHERE session_id=%s",
        (WORKER_SESSION,),
    )
    steering_scope.commit()

    report = _compose(steering_scope)
    holder = next(row for row in report.idle if row.session_id == WORKER_SESSION)
    assert holder.native_process_gone is True
    body = report_body(report)
    assert "process gone, claims held — terminate deliberately if dead" in body
    holder_line = next(line for line in body.splitlines() if WORKER_SESSION in line)
    assert "wake `" not in holder_line


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


def _register_live_launch(
    conn, session_id: str, *, origin: str, launch_id: str
) -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'launch instruction', 'sha', %s, %s, %s)",
        (f"msg-{launch_id}", ACTOR_ID, STEERING_SESSION, json.dumps({}), LONG_AGO, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, assigned_machine_id, "
        "registered_session_id) "
        "VALUES (%s, %s, %s, 'codex-cli', 'codex-cli', 0, %s, 'succeeded', "
        "%s, %s, %s, 'machine-1', %s)",
        (
            launch_id,
            ACTOR_ID,
            PROJECT_ID,
            f"msg-{launch_id}",
            NOW,
            LONG_AGO,
            origin,
            session_id,
        ),
    )


def test_launch_balance_splits_live_sessions_by_origin(steering_scope):
    _register_live_launch(
        steering_scope, WORKER_SESSION, origin=LAUNCH_ORIGIN_OPERATOR, launch_id="op-1"
    )
    _register_live_launch(
        steering_scope,
        STEERING_SESSION,
        origin=LAUNCH_ORIGIN_STEERING,
        launch_id="st-1",
    )
    steering_scope.commit()

    body = report_body(_compose(steering_scope))

    assert "origin operator 1 · steering 1" in body


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
        "undelivered messages",
        "unregistered launches",
        "landed without close-out",
        "suspected orphaned waiter",
        "dead waits",
    ):
        assert absent not in body
    assert ": none" not in body.replace("launchable machine/surface pairs: none", "")

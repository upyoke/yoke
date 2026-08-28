"""What the fleet report notices, and what it deliberately stays quiet about."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_fleet_report import compose_report
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.work_claim_targets import make_item_target


NOW = "2026-08-26T12:00:00Z"
LONG_AGO = "2026-08-26T09:00:00Z"
JUST_NOW = "2026-08-26T11:58:00Z"
STALE_SECONDS = 20 * 60
SURFACE = "codex-cli"
STEERING_SESSION = "steering-holder"
WORKER_SESSION = "another-worker"
PROJECT_ID = 1
ACTOR_ID = 2


def _seed_session(conn, session_id: str, **columns) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface, last_tool_call_at, ended_at) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            f"/tmp/{session_id}",
            PROJECT_ID,
            columns.get("mode", "wait"),
            NOW,
            NOW,
            ACTOR_ID,
            SURFACE,
            columns.get("last_tool_call_at"),
            columns.get("ended_at"),
        ),
    )


def _seed_relay(conn) -> None:
    conn.execute(
        "INSERT INTO session_relays "
        "(relay_id, actor_id, machine_id, hostname, surface_versions, "
        "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
        "VALUES ('relay-1', %s, 'machine-1', 'relay-host', %s, %s, %s, %s, "
        "%s, 'active')",
        (
            ACTOR_ID,
            json.dumps({SURFACE: "0.148.0a15"}),
            json.dumps([PROJECT_ID]),
            NOW,
            NOW,
            "2026-08-26T23:00:00Z",
        ),
    )


def _compose(conn, session_id: str = STEERING_SESSION):
    return compose_report(
        conn,
        project_id=PROJECT_ID,
        session_id=session_id,
        stale_after_seconds=STALE_SECONDS,
        now=NOW,
    )


@pytest.fixture
def steering_scope(test_db):
    """A steering holder, a connected relay, and three long-unpicked items."""
    _seed_session(test_db, STEERING_SESSION)
    _seed_session(test_db, WORKER_SESSION, last_tool_call_at=LONG_AGO)
    _seed_relay(test_db)
    for item_id in (1, 2, 3):
        insert_item(
            test_db,
            id=item_id,
            title=f"Unpicked work {item_id}",
            status="idea",
            created_at=LONG_AGO,
            updated_at=LONG_AGO,
            spec=f"# Unpicked work {item_id}\n\nA real spec body.",
        )
    test_db.commit()
    acquire_steering(
        test_db,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        reason="steering",
    )
    return test_db


def test_work_nobody_ever_picked_up_reports_as_unstaffed(steering_scope):
    report = _compose(steering_scope)

    assert {entry.item_id for entry in report.unstaffed} == {1, 2, 3}
    assert report.unowned == ()
    assert report.actionable is True


def test_work_whose_owner_was_released_reports_as_unowned(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(2),
    )
    steering_scope.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'reclaimed' "
        "WHERE session_id = %s",
        (LONG_AGO, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert {entry.item_id for entry in report.unowned} == {2}
    assert {entry.item_id for entry in report.unstaffed} == {1, 3}


def test_a_claim_released_moments_ago_is_not_yet_reported(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(2),
    )
    steering_scope.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'released' "
        "WHERE session_id = %s",
        (JUST_NOW, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert 2 in {entry.item_id for entry in report.frontier}
    assert 2 not in {entry.item_id for entry in report.unowned}
    assert 2 not in {entry.item_id for entry in report.unstaffed}


def test_work_someone_holds_is_not_on_the_frontier(steering_scope):
    for item_id in (1, 2, 3):
        claim_work(
            steering_scope,
            session_id=WORKER_SESSION,
            target=make_item_target(item_id),
        )

    report = _compose(steering_scope)

    assert report.frontier == ()
    assert report.unstaffed == ()
    assert {holder.item_id for holder in report.holders} == {1, 2, 3}


def test_a_quiet_holder_reports_as_idle(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )

    report = _compose(steering_scope)

    assert {holder.item_id for holder in report.idle} == {1}
    assert report.idle[0].session_id == WORKER_SESSION


def test_a_parked_holder_declared_its_wait_and_is_not_idle(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    steering_scope.execute(
        "UPDATE harness_sessions SET mode = 'parked' WHERE session_id = %s",
        (WORKER_SESSION,),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert report.idle == ()
    assert {holder.item_id for holder in report.holders} == {1}
    assert report.holders[0].parked is True


def test_an_ended_session_is_not_a_holder_at_all(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    steering_scope.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert report.holders == ()
    assert report.idle == ()


def test_launchability_names_the_connected_machine_and_surface(steering_scope):
    report = _compose(steering_scope)

    assert (
        "machine-1",
        SURFACE,
    ) in {(ready.machine_id, ready.surface) for ready in report.launchable}


def test_the_fingerprint_ignores_how_old_everything_is(steering_scope):
    early = _compose(steering_scope)
    later = compose_report(
        steering_scope,
        project_id=PROJECT_ID,
        session_id=STEERING_SESSION,
        stale_after_seconds=STALE_SECONDS,
        now="2026-08-26T12:30:00Z",
    )

    assert early.fingerprint() == later.fingerprint()


def test_the_body_leads_with_what_needs_a_decision(steering_scope):
    body = report_body(_compose(steering_scope))

    assert body.startswith("=== BEGIN YOKE FLEET REPORT ===")
    assert body.index("unstaffed") < body.index("frontier")
    assert "not instructions" in body
    assert "YOK-1" in body

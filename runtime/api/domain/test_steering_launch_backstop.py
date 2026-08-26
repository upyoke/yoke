"""End-to-end staffing behavior for the steering launch backstop."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_OPERATOR,
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchRequest,
    SessionLaunchError,
)
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_launch_backstop import run_backstop
from yoke_core.domain.work_claim_targets import make_item_target


NOW = "2026-08-26T12:00:00Z"
LONG_AGO = "2026-08-26T09:00:00Z"
JUST_NOW = "2026-08-26T11:58:00Z"
GRACE_SECONDS = 20 * 60
SURFACE = "codex-cli"
STEERING_SESSION = "steering-holder"
WORKER_SESSION = "another-worker"
PROJECT_ID = 1
ACTOR_ID = 2


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "'wait', %s, %s, %s, %s)",
        (session_id, f"/tmp/{session_id}", PROJECT_ID, NOW, NOW, ACTOR_ID, SURFACE),
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


def _authorization() -> LaunchAuthorization:
    return LaunchAuthorization(
        actor_id=ACTOR_ID,
        session_id=STEERING_SESSION,
        can_operate_project=True,
        can_administer_project=True,
    )


@pytest.fixture
def steering_scope(test_db):
    """A steering holder, a connected relay, and three long-unpicked items."""
    _seed_session(test_db, STEERING_SESSION)
    _seed_session(test_db, WORKER_SESSION)
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


def _evaluate(conn, *, worker_budget: int = 2, dry_run: bool = False):
    return run_backstop(
        conn,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        auth=_authorization(),
        executor_surface=SURFACE,
        unpicked_after_seconds=GRACE_SECONDS,
        worker_budget=worker_budget,
        dry_run=dry_run,
        now=NOW,
    )


def _launch_rows(conn):
    return conn.execute(
        "SELECT launch_id, origin, message_id FROM session_launches "
        "ORDER BY created_at, launch_id"
    ).fetchall()


def test_unpicked_work_is_staffed_up_to_the_budget(steering_scope):
    result = _evaluate(steering_scope)

    assert len(result["launched"]) == 2
    assert len(result["withheld"]) == 1
    rows = [dict(row) for row in _launch_rows(steering_scope)]
    assert len(rows) == 2
    assert {row["origin"] for row in rows} == {LAUNCH_ORIGIN_STEERING_BACKSTOP}
    assert all(
        entry["launch"]["origin"] == LAUNCH_ORIGIN_STEERING_BACKSTOP
        for entry in result["launched"]
    )


def test_a_staffed_worker_is_told_which_item_and_who_to_report_to(steering_scope):
    _evaluate(steering_scope, worker_budget=1)

    body = dict(
        steering_scope.execute(
            "SELECT body FROM session_messages ORDER BY created_at LIMIT 1"
        ).fetchone()
    )["body"]
    assert "/yoke " in body.splitlines()[0]
    assert f"yoke say --stdin --session {STEERING_SESSION}" in body


def test_work_someone_already_claimed_is_not_staffed(steering_scope):
    for item_id in (1, 2, 3):
        claim_work(
            steering_scope,
            session_id=WORKER_SESSION,
            target=make_item_target(item_id),
        )

    result = _evaluate(steering_scope)

    assert result["staff"] == []
    assert result["launched"] == []
    assert _launch_rows(steering_scope) == []


def test_work_that_only_just_became_pickable_is_left_alone(test_db):
    _seed_session(test_db, STEERING_SESSION)
    _seed_relay(test_db)
    insert_item(
        test_db,
        id=4,
        title="Fresh work",
        status="idea",
        created_at=JUST_NOW,
        updated_at=JUST_NOW,
        spec="# Fresh work\n\nA real spec body.",
    )
    test_db.commit()
    acquire_steering(
        test_db, session_id=STEERING_SESSION, project_id=PROJECT_ID, reason="steering"
    )

    result = _evaluate(test_db)

    assert result["staff"] == []
    assert result["withheld"][0]["reason"] == "within_grace_period"
    assert _launch_rows(test_db) == []


def test_a_second_evaluation_moves_on_instead_of_restaffing(steering_scope):
    _evaluate(steering_scope, worker_budget=2)

    result = _evaluate(steering_scope, worker_budget=3)

    assert result["workers_in_flight"] == 2
    assert [entry["item_id"] for entry in result["launched"]] == [3]
    assert {entry["reason"] for entry in result["withheld"]} == {"already_staffed"}
    assert len(_launch_rows(steering_scope)) == 3


def test_a_gap_whose_worker_ended_reuses_that_launch(steering_scope):
    _evaluate(steering_scope, worker_budget=2)
    steering_scope.execute(
        "UPDATE session_launches SET state = 'cancelled', completed_at = %s",
        (NOW,),
    )

    result = _evaluate(steering_scope, worker_budget=2)

    assert result["workers_in_flight"] == 0
    assert [entry["deduplicated"] for entry in result["launched"]] == [True, True]
    assert len(_launch_rows(steering_scope)) == 2


def test_workers_already_in_flight_spend_the_budget(steering_scope):
    _evaluate(steering_scope, worker_budget=2)

    result = _evaluate(steering_scope, worker_budget=2)

    assert result["workers_in_flight"] == 2
    assert result["headroom"] == 0
    assert result["launched"] == []


def test_an_operator_launch_does_not_spend_the_backstop_budget(steering_scope):
    create_launch(
        steering_scope,
        auth=_authorization(),
        request=LaunchRequest(
            project_id=PROJECT_ID,
            executor_surface=SURFACE,
            instructions="Operator-requested work.",
            idempotency_key="operator-key",
        ),
        now=NOW,
    )

    result = _evaluate(steering_scope, worker_budget=2)

    assert result["workers_in_flight"] == 0
    assert len(result["launched"]) == 2
    origins = {dict(row)["origin"] for row in _launch_rows(steering_scope)}
    assert origins == {LAUNCH_ORIGIN_OPERATOR, LAUNCH_ORIGIN_STEERING_BACKSTOP}


def test_dry_run_decides_without_filing_a_launch(steering_scope):
    result = _evaluate(steering_scope, dry_run=True)

    assert len(result["staff"]) == 2
    assert result["launched"] == []
    assert _launch_rows(steering_scope) == []


def test_a_session_without_the_steering_claim_is_refused(steering_scope):
    with pytest.raises(SessionLaunchError) as refused:
        run_backstop(
            steering_scope,
            session_id=WORKER_SESSION,
            project_id=PROJECT_ID,
            auth=_authorization(),
            executor_surface=SURFACE,
            unpicked_after_seconds=GRACE_SECONDS,
            worker_budget=2,
            now=NOW,
        )

    assert refused.value.code == "steering_claim_required"

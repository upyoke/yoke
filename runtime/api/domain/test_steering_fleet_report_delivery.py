"""When a delivery carries the fleet report, and when it stays silent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.strategy_docs_defaults import seed_default_docs
from yoke_core.domain.steering_fleet_report_delivery import (
    confirm_steering_report_delivery,
    steered_project_id,
    steering_report_candidate,
    steering_report_for_delivery,
)


NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
LONG_AGO = "2026-08-26T09:00:00Z"
STEERING_SESSION = "steering-holder"
PLAIN_SESSION = "ordinary-worker"
PROJECT_ID = 1
ACTOR_ID = 2


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "'wait', %s, %s, %s, 'codex-cli')",
        (
            session_id,
            f"/tmp/{session_id}",
            PROJECT_ID,
            LONG_AGO,
            LONG_AGO,
            ACTOR_ID,
        ),
    )


def _last_report(conn, session_id: str) -> tuple[str, str]:
    row = dict(
        conn.execute(
            "SELECT last_steering_report_at, last_steering_report_fingerprint "
            "FROM harness_sessions WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    )
    return (
        str(row["last_steering_report_at"] or ""),
        str(row["last_steering_report_fingerprint"] or ""),
    )


@pytest.fixture
def steering_scope(test_db):
    """A steering holder, an ordinary session, and one long-unpicked item."""
    _seed_session(test_db, STEERING_SESSION)
    _seed_session(test_db, PLAIN_SESSION)
    insert_item(
        test_db,
        id=1,
        title="Unpicked work",
        status="idea",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        spec="# Unpicked work\n\nA real spec body.",
    )
    test_db.commit()
    seed_default_docs(test_db, PROJECT_ID, "Yoke")
    acquire_steering(
        test_db,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        reason="steering",
    )
    return test_db


def test_a_session_without_the_seat_is_owed_nothing(steering_scope):
    assert steered_project_id(steering_scope, PLAIN_SESSION) is None
    assert (
        steering_report_for_delivery(steering_scope, session_id=PLAIN_SESSION, now=NOW)
        is None
    )


def test_the_steering_seat_receives_the_report(steering_scope):
    body = steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    assert body is not None
    assert "=== BEGIN YOKE FLEET REPORT ===" in body
    stamped_at, fingerprint = _last_report(steering_scope, STEERING_SESSION)
    assert stamped_at
    assert fingerprint


def test_an_unconfirmed_candidate_does_not_take_the_interval(steering_scope):
    """Peeking a candidate composes it without spending its delivery slot.

    A reply that turns out denied or malformed must not cost the recipient
    a whole interval's report — the next hook has to see the SAME candidate
    again rather than a suppressed one, because nothing was ever confirmed.
    """
    first = steering_report_candidate(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    assert first is not None
    assert "=== BEGIN YOKE FLEET REPORT ===" in first.text
    stamped_at, fingerprint = _last_report(steering_scope, STEERING_SESSION)
    assert stamped_at == ""
    assert fingerprint == ""

    second = steering_report_candidate(
        steering_scope, session_id=STEERING_SESSION, now=NOW + timedelta(minutes=1)
    )

    assert second is not None
    assert second.fingerprint == first.fingerprint


def test_confirming_a_candidate_takes_the_interval_for_the_next_peek(steering_scope):
    candidate = steering_report_candidate(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    assert candidate is not None

    assert confirm_steering_report_delivery(steering_scope, candidate) is True
    stamped_at, fingerprint = _last_report(steering_scope, STEERING_SESSION)
    assert stamped_at
    assert fingerprint == candidate.fingerprint

    assert (
        steering_report_candidate(
            steering_scope,
            session_id=STEERING_SESSION,
            now=NOW + timedelta(minutes=1),
        )
        is None
    )


def test_a_second_delivery_inside_the_interval_carries_nothing(steering_scope):
    assert steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    assert (
        steering_report_for_delivery(
            steering_scope,
            session_id=STEERING_SESSION,
            now=NOW + timedelta(minutes=1),
        )
        is None
    )


def test_unchanged_quiet_content_is_suppressed_but_still_takes_the_interval(
    steering_scope,
):
    steering_scope.execute("DELETE FROM items WHERE id = 1")
    steering_scope.commit()
    later = NOW + timedelta(minutes=30)

    first = steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    assert first is not None  # the first report is always new to this session
    _, fingerprint = _last_report(steering_scope, STEERING_SESSION)

    assert (
        steering_report_for_delivery(
            steering_scope, session_id=STEERING_SESSION, now=later
        )
        is None
    )
    stamped_at, unchanged = _last_report(steering_scope, STEERING_SESSION)
    assert unchanged == fingerprint
    assert stamped_at == "2026-08-26T12:30:00Z"


def test_changed_content_reports_again_after_the_interval(steering_scope):
    assert steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )
    insert_item(
        steering_scope,
        id=2,
        title="More unpicked work",
        status="idea",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        spec="# More unpicked work\n\nA real spec body.",
    )
    steering_scope.commit()

    body = steering_report_for_delivery(
        steering_scope,
        session_id=STEERING_SESSION,
        now=NOW + timedelta(minutes=30),
    )

    assert body is not None
    assert "YOK-2" in body


QUIET_PROJECT_ID = 2


def _hold_second_scope(conn) -> None:
    seed_default_docs(conn, QUIET_PROJECT_ID, "ExternalWebapp")
    acquire_steering(
        conn,
        session_id=STEERING_SESSION,
        project_id=QUIET_PROJECT_ID,
        reason="steering",
    )


def test_a_quiet_scope_overdue_row_rides_any_wake(steering_scope):
    steering_scope.execute("DELETE FROM items WHERE id = 1")
    steering_scope.commit()
    _hold_second_scope(steering_scope)
    insert_item(
        steering_scope,
        id=59,
        title="Aging quiet work",
        status="idea",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        project_id=QUIET_PROJECT_ID,
        spec="# Aging quiet work\n\nA real spec body.",
    )

    body = steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    assert body is not None
    assert "## externalwebapp" in body
    assert "Aging quiet work" in body
    assert "!" in body


def test_a_change_in_either_held_scope_reports_again(steering_scope):
    _hold_second_scope(steering_scope)
    assert steering_report_for_delivery(
        steering_scope, session_id=STEERING_SESSION, now=NOW
    )

    insert_item(
        steering_scope,
        id=59,
        title="Quiet-scope change",
        status="idea",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        project_id=QUIET_PROJECT_ID,
        spec="# Quiet-scope change\n\nA real spec body.",
    )

    body = steering_report_for_delivery(
        steering_scope,
        session_id=STEERING_SESSION,
        now=NOW + timedelta(minutes=30),
    )

    assert body is not None
    assert "## externalwebapp" in body
    assert "Quiet-scope change" in body

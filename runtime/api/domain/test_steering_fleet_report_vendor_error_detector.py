"""Finding the workers a project lost to the model provider.

The detector's whole job is to read state no other detector reads as a
failure: a live session, holding its claim, that will never speak again.
These cases pin the parts a unit test of the decision logic cannot — that
the item stalled behind the worker is named, that a worker stopped on some
other machine still reaches its project's steerer, and that an ordinary
fleet produces nothing.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
)
from yoke_core.domain.session_native_turn_end import EVENT_SESSION_TURN_END_OBSERVED
from yoke_core.domain.steering_fleet_report_vendor_errors import (
    vendor_error_sessions,
)


STOPPED_SESSION = "stopped-worker"
STOPPED_AT = "2026-08-26T11:40:00Z"
LIVE_ERROR = (
    "unexpected status 404 Not Found: Unknown error, url: "
    "https://chatgpt.com/backend-api/codex/responses"
)


def _observe(conn, session_id: str, *, at: str = STOPPED_AT) -> None:
    """Record the turn-end observation the relay's record read produced."""
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_kind, event_type, "
        "source_type, session_id, envelope, created_at) "
        "VALUES (%s, %s, 'system', 'session_lifecycle', 'backend', %s, %s, %s)",
        (
            f"observed-{session_id}",
            EVENT_SESSION_TURN_END_OBSERVED,
            session_id,
            json.dumps(
                {
                    "context": {
                        "observed_at": at,
                        "codex_error_info": "other",
                        "error_message": LIVE_ERROR,
                    }
                }
            ),
            at,
        ),
    )
    conn.commit()


def _claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        "INSERT INTO work_claims "
        "(target_kind, scope, session_id, claimed_at, last_heartbeat, reason) "
        "VALUES ('item', %s, %s, %s, %s, 'implementing')",
        (json.dumps({"item_id": item_id}), session_id, LONG_AGO, LONG_AGO),
    )
    conn.commit()


@pytest.fixture
def fleet(test_db):
    """One worker holding one item, before anything has gone wrong."""
    insert_item(
        test_db,
        id=1,
        title="Work behind a stopped worker",
        status="implementing",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        spec="# Work behind a stopped worker\n\nA real spec body.",
    )
    seed_session(test_db, STOPPED_SESSION, last_tool_call_at=LONG_AGO)
    _claim(test_db, STOPPED_SESSION, 1)
    return test_db


def test_an_ordinary_fleet_reports_nothing(fleet):
    assert vendor_error_sessions(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_stopped_worker_is_named_with_the_item_it_is_holding(fleet):
    _observe(fleet, STOPPED_SESSION)

    rows = vendor_error_sessions(fleet, project_id=PROJECT_ID, now=NOW)

    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == STOPPED_SESSION
    assert row.public_ref == "YOK-1"
    assert row.item_id == 1
    assert row.signature_id == "client_refused"
    assert row.error_message == LIVE_ERROR
    assert row.observed_at == STOPPED_AT
    assert row.stopped_seconds == 20 * 60
    assert row.seat_owed is False


def test_a_worker_stopped_on_another_machine_still_reaches_its_steerer(test_db):
    """The seat's scope is a project; the relay's is one machine.

    A worker the seat cannot see is exactly the one whose silence goes
    unexplained, so scoping this detector to the composing machine would
    reproduce the invisibility it exists to remove.
    """
    seed_session(
        test_db, "elsewhere", machine_id="machine-99", last_tool_call_at=LONG_AGO
    )
    _observe(test_db, "elsewhere")

    rows = vendor_error_sessions(test_db, project_id=PROJECT_ID, now=NOW)

    assert [row.session_id for row in rows] == ["elsewhere"]
    # Holding no claim is not a reason to hide it; it is a reason to say so.
    assert rows[0].public_ref == ""


def test_a_worker_that_has_since_run_a_tool_is_no_longer_stopped(fleet):
    _observe(fleet, STOPPED_SESSION)
    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        ("2026-08-26T11:50:00Z", STOPPED_SESSION),
    )
    fleet.commit()

    assert vendor_error_sessions(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_ended_session_is_the_sweep_s_business_not_this_report_s(fleet):
    _observe(fleet, STOPPED_SESSION)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (NOW, STOPPED_SESSION),
    )
    fleet.commit()

    assert vendor_error_sessions(fleet, project_id=PROJECT_ID, now=NOW) == ()

"""Quiet because it is working, versus quiet because it is stuck.

A worker inside one foreground merge wait or CI-routed QA gate makes no new
tool call for tens of minutes. Every wrong answer here costs the seat a pass:
calling a working holder idle sends it a probe or restaffs its item, and
calling a dead turn's leftover rows "in flight" hides a holder that really has
stopped.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    WORKER_SESSION,
    compose as _compose,
    quiet_holder,
    seed_denial,
    seed_steering_scope,
    seed_tool_call,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_report_in_flight import (
    IN_FLIGHT_CEILING_SECONDS,
    in_flight_calls,
    long_running_command,
)
from yoke_core.domain.work_claim_targets import make_item_target


#: Twenty minutes before ``NOW``: past the report's idle threshold, well
#: inside every long-running command's own budget.
CALL_STARTED = "2026-08-26T11:40:00Z"
#: Two hours before ``NOW``: past :data:`IN_FLIGHT_CEILING_SECONDS`.
CALL_STARTED_LONG_OVER = "2026-08-26T10:00:00Z"

MERGE_WAIT = (
    "cd /repo/.worktrees/YOK-1 && yoke --env prod watch merge "
    "merge-item -- YOK-1 --wait --result done"
)


@pytest.fixture
def fleet(test_db):
    """One quiet holder on item 1, before any open call is introduced."""
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    return conn


def _open_call(conn, command: str, *, started_at: str = CALL_STARTED) -> None:
    seed_tool_call(
        conn,
        WORKER_SESSION,
        tool_use_id="call-1",
        started_at=started_at,
        command_summary=command,
    )
    conn.commit()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (MERGE_WAIT, "watch merge"),
        ("yoke watch qa-case run --requirement-id 7", "watch qa-case"),
        ("yoke watch pytest --impacted main --bounded", "watch pytest"),
        ("yoke --env prod watch deploy -- run-20260826-001", "watch deploy"),
        ("yoke watch preflight -- stage-db-admin", "watch preflight"),
        ("yoke watch doctor -- --full", "watch doctor"),
        (
            "python3 -m yoke_core.tools.watch_pytest -- tests/",
            "yoke_core.tools.watch_pytest",
        ),
        ("yoke merge item YOK-1 --wait --result done", "merge item --wait"),
        ("yoke merge item YOK-1 --result done", None),
        ("git -C /repo log -3 --oneline", None),
        ("", None),
    ],
)
def test_only_the_known_long_running_shapes_are_recognized(command, expected):
    assert long_running_command(command) == expected


def test_a_holder_inside_a_merge_wait_is_in_flight_and_raises_no_idle_alarm(fleet):
    _open_call(fleet, MERGE_WAIT)

    report = _compose(fleet)

    assert [call.session_id for call in report.in_flight] == [WORKER_SESSION]
    assert report.in_flight[0].command == "watch merge"
    assert report.in_flight[0].item_id == 1
    assert report.idle == ()
    assert {holder.session_id for holder in report.holders} == {WORKER_SESSION}


def test_the_in_flight_row_names_the_command_and_when_it_opened(fleet):
    from yoke_core.domain.steering_fleet_report_render import report_body

    _open_call(fleet, MERGE_WAIT)

    body = report_body(_compose(fleet))

    assert "in watch merge since 11:40Z" in body
    assert "idle holders" not in body


def test_an_open_row_left_by_a_denied_call_does_not_suppress_the_idle_alarm(fleet):
    """A refused call ran for zero seconds; a dead turn leaves one row apiece."""
    _open_call(fleet, MERGE_WAIT)
    seed_denial(fleet, WORKER_SESSION, tool_use_id="call-1", at=CALL_STARTED)
    fleet.commit()

    report = _compose(fleet)

    assert report.in_flight == ()
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}


def test_an_ordinary_open_row_does_not_suppress_the_idle_alarm(fleet):
    _open_call(fleet, "git -C /repo status --short")

    report = _compose(fleet)

    assert report.in_flight == ()
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}


def test_a_holder_with_no_open_call_at_all_stays_idle(fleet):
    report = _compose(fleet)

    assert report.in_flight == ()
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}


def test_a_call_open_past_the_ceiling_rejoins_the_idle_alarm(fleet):
    """Past its own command's budget, a call the seat cannot see is a finding."""
    _open_call(fleet, MERGE_WAIT, started_at=CALL_STARTED_LONG_OVER)

    report = _compose(fleet)

    assert report.in_flight == ()
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}


def test_a_row_the_session_kept_working_past_is_residue_rather_than_in_flight(fleet):
    """Activity recorded after the call opened proves it already finished."""
    seed_tool_call(
        fleet,
        WORKER_SESSION,
        tool_use_id="call-1",
        started_at="2026-08-26T08:00:00Z",
        command_summary=MERGE_WAIT,
    )
    fleet.commit()

    calls = in_flight_calls(fleet, quiet=[quiet_holder(WORKER_SESSION)], now=NOW)

    assert calls == ()


def test_a_completed_call_is_not_in_flight(fleet):
    seed_tool_call(
        fleet,
        WORKER_SESSION,
        tool_use_id="call-1",
        started_at=CALL_STARTED,
        command_summary=MERGE_WAIT,
        completed_at=NOW,
    )
    fleet.commit()

    assert _compose(fleet).in_flight == ()


def test_the_newest_open_row_decides_rather_than_any_older_leftover(fleet):
    """Residue accumulates on harnesses that never close a row."""
    _open_call(fleet, MERGE_WAIT, started_at=LONG_AGO)
    seed_tool_call(
        fleet,
        WORKER_SESSION,
        tool_use_id="call-2",
        started_at=CALL_STARTED,
        command_summary="git -C /repo status --short",
    )
    fleet.commit()

    report = _compose(fleet)

    assert report.in_flight == ()
    assert {holder.session_id for holder in report.idle} == {WORKER_SESSION}


def test_the_ceiling_is_the_widest_budget_these_commands_give_themselves():
    from yoke_core.domain.merge_queue_landing_wait import DEFAULT_DEADLINE_SECONDS

    assert IN_FLIGHT_CEILING_SECONDS == int(DEFAULT_DEADLINE_SECONDS)

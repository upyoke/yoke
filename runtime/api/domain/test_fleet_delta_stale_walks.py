"""Stale-walk alarms: one line per silent walk, folded into idle-holder lines."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.project_contract.project_keys import DEFAULT_SESSION_IDLE_MINUTES

from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_lines import compare
from yoke_core.domain.fleet_delta_snapshot import (
    FleetSnapshot,
    SessionRow,
    WalkRow,
    session_rows,
)

NOW = datetime(2026, 11, 19, 16, 30, tzinfo=timezone.utc)
OWNER = "019e41e1-9b2c-7a41-8f30-6d5a0c7b2e14"


def _walk(silent_minutes: int) -> WalkRow:
    return WalkRow(
        execution_id="exec-1f35f350",
        item="YOK-5475",
        test_machine="test-mac-studio",
        heartbeat_at=NOW - timedelta(minutes=silent_minutes),
    )


def _owner(*walks: WalkRow, idle: bool = False, **overrides) -> SessionRow:
    activity = NOW - timedelta(minutes=DEFAULT_SESSION_IDLE_MINUTES + 5 if idle else 1)
    fields = {
        "session_id": OWNER,
        "executor_surface": "claude-cli",
        "mode": "dash",
        "parked": False,
        "ended": False,
        "terminated": False,
        "activity_at": activity,
        "last_tool_call_at": activity,
        "claimed_items": ("YOK-5475",),
        "walks": walks,
    }
    fields.update(overrides)
    return SessionRow(**fields)


def _pass(row: SessionRow, state: DeltaState, *, at: datetime = NOW) -> list[str]:
    snapshot = FleetSnapshot(
        taken_at=at, self_session_id="steerer", sessions={row.session_id: row}
    )
    return [
        line
        for line in compare(None, snapshot, state)
        if "walk" in line or "idle-holder" in line
    ]


def test_a_silent_walk_alarms_once_then_clears_when_it_heartbeats() -> None:
    state = DeltaState()
    assert _pass(_owner(_walk(21)), state) == [
        "fleet ALARM stale-walk execution=exec-1f35f350 item=YOK-5475 "
        f"host=test-mac-studio silent=21m session={OWNER}"
    ]
    assert _pass(_owner(_walk(22)), state) == []
    assert _pass(_owner(_walk(0)), state) == [
        "fleet CLEAR stale-walk execution=exec-1f35f350"
    ]
    assert _pass(_owner(_walk(1)), state) == []


def test_a_walk_that_ends_clears_its_alarm() -> None:
    state = DeltaState()
    assert _pass(_owner(_walk(25)), state)
    assert _pass(_owner(), state) == ["fleet CLEAR stale-walk execution=exec-1f35f350"]


def test_below_the_line_or_parked_owners_raise_nothing() -> None:
    assert _pass(_owner(_walk(19)), DeltaState()) == []
    assert _pass(_owner(_walk(25), parked=True, mode="parked"), DeltaState()) == []


def test_an_idle_holder_carries_the_walk_and_no_separate_line_prints() -> None:
    state = DeltaState()
    lines = _pass(_owner(_walk(24), idle=True), state)
    assert len(lines) == 1
    assert lines[0].startswith(f"fleet ALARM idle-holder session={OWNER} ")
    assert lines[0].endswith(" stale_walk=exec-1f35f350:24m")
    assert not any("ALARM stale-walk" in line for line in lines)


def test_a_walk_going_silent_under_an_alarmed_idle_holder_reprints_its_line() -> None:
    state = DeltaState()
    first = _pass(_owner(_walk(5), idle=True), state)
    assert first and "stale_walk=" not in first[0]
    later = NOW + timedelta(minutes=16)
    again = _pass(_owner(_walk(5), idle=True), state, at=later)
    assert len(again) == 1
    assert again[0].endswith(" stale_walk=exec-1f35f350:21m")
    assert _pass(_owner(_walk(5), idle=True), state, at=later) == []


def test_the_roster_field_becomes_walk_rows_and_its_absence_is_none() -> None:
    raw = {
        "session_id": OWNER,
        "silent_walks": [
            {
                "execution_id": "exec-1f35f350",
                "item": "YOK-5475",
                "test_machine": "test-mac-studio",
                "heartbeat_at": "2026-11-19T15:46:00Z",
            }
        ],
    }
    walks = session_rows({"rows": [raw]})[OWNER].walks
    assert walks == (
        WalkRow(
            execution_id="exec-1f35f350",
            item="YOK-5475",
            test_machine="test-mac-studio",
            heartbeat_at=datetime(2026, 11, 19, 15, 46, tzinfo=timezone.utc),
        ),
    )
    assert session_rows({"rows": [{"session_id": OWNER}]})[OWNER].walks == ()

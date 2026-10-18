"""Unstaffed-ready alarms follow the report's overdue available set."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, ItemRow
from yoke_core.domain.fleet_delta_unstaffed import unstaffed_ready_alarms
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_available import (
    FrontierEntry,
    is_unstaffed_ready,
)

NOW = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
THRESHOLD = 5 * 60


def _item(**overrides) -> ItemRow:
    fields = {
        "ref": "YOK-1",
        "status": "implementing",
        "title": "Work",
        "claim_state": "unclaimed",
        "project": "yoke",
        "runnable": True,
        "rank": 2,
        "next_step": "dash",
        "launch_state": "",
        "pickable_since": NOW - timedelta(minutes=6),
        "staffing_after_seconds": THRESHOLD,
    }
    fields.update(overrides)
    return ItemRow(**fields)


def _snapshot(*items: ItemRow, taken_at: datetime = NOW) -> FleetSnapshot:
    return FleetSnapshot(
        taken_at=taken_at,
        self_session_id="steerer",
        items={item.ref: item for item in items},
    )


def test_overdue_available_item_alarms_once_with_its_reach_command() -> None:
    state = DeltaState()
    fired = unstaffed_ready_alarms(_snapshot(_item()), state)
    assert len(fired) == 1
    line = fired[0]
    assert line.startswith("fleet ALARM unstaffed-ready ")
    assert "item=YOK-1" in line
    assert "project=yoke" in line
    assert "waiting=6m" in line
    assert "rank=2" in line
    assert "next=dash" in line
    assert (
        "yoke session-control launch create --project yoke --item YOK-1 "
        '--idempotency-key "steer:yoke:YOK-1" --json'
    ) in line
    assert unstaffed_ready_alarms(_snapshot(_item()), state) == []


def test_launch_in_flight_suppresses_the_alarm_and_ends_the_episode() -> None:
    state = DeltaState()
    assert unstaffed_ready_alarms(_snapshot(_item()), state)
    assert unstaffed_ready_alarms(_snapshot(_item(launch_state="assigned")), state) == [
        "fleet CLEAR unstaffed-ready item=YOK-1"
    ]
    assert (
        unstaffed_ready_alarms(
            _snapshot(_item(launch_state="awaiting_registration")), DeltaState()
        )
        == []
    )


def test_staffing_ends_the_episode() -> None:
    state = DeltaState()
    unstaffed_ready_alarms(_snapshot(_item()), state)
    assert unstaffed_ready_alarms(
        _snapshot(_item(claim_state="claimed_by_other_live")), state
    ) == ["fleet CLEAR unstaffed-ready item=YOK-1"]


def test_repeat_fires_after_the_staffing_interval() -> None:
    state = DeltaState()
    assert unstaffed_ready_alarms(_snapshot(_item()), state)
    assert (
        unstaffed_ready_alarms(
            _snapshot(_item(), taken_at=NOW + timedelta(seconds=THRESHOLD - 1)),
            state,
        )
        == []
    )
    fired = unstaffed_ready_alarms(
        _snapshot(_item(), taken_at=NOW + timedelta(seconds=THRESHOLD)),
        state,
    )
    assert len(fired) == 1
    assert fired[0].startswith("fleet ALARM unstaffed-ready ")


def test_waiting_under_the_threshold_is_silent() -> None:
    item = _item(pickable_since=NOW - timedelta(minutes=4))
    assert unstaffed_ready_alarms(_snapshot(item), DeltaState()) == []


def test_a_schedule_row_without_the_report_clock_does_not_alarm() -> None:
    item = _item(pickable_since=None, staffing_after_seconds=0)
    assert unstaffed_ready_alarms(_snapshot(item), DeltaState()) == []


def test_predicate_matches_the_report_overdue_set() -> None:
    overdue = FrontierEntry(
        item_id=1,
        public_ref="YOK-1",
        title="Work",
        next_step="dash",
        rank=2,
        pickable_since=NOW - timedelta(minutes=6),
        was_owned=False,
    )
    launched = FrontierEntry(
        item_id=2,
        public_ref="YOK-2",
        title="Launching",
        next_step="dash",
        rank=3,
        pickable_since=NOW - timedelta(minutes=6),
        was_owned=False,
        launch_state="assigned",
    )
    fresh = FrontierEntry(
        item_id=3,
        public_ref="YOK-3",
        title="Fresh",
        next_step="dash",
        rank=4,
        pickable_since=NOW - timedelta(minutes=1),
        was_owned=False,
    )
    report = FleetReport(
        project_id=1,
        composed_at=NOW,
        staffing_after_seconds=THRESHOLD,
        idle_after_seconds=20 * 60,
        available=(overdue, launched, fresh),
        holders=(),
        idle=(),
        undelivered=(),
        unregistered_launches=(),
        landed_open=(),
        dead_waits=(),
        launchable=(),
        session_counts=(),
    )
    matched = [
        entry.public_ref
        for entry in report.available
        if is_unstaffed_ready(
            entry.launch_state,
            entry.waiting_seconds(report.composed_at),
            report.staffing_after_seconds,
        )
    ]
    assert matched == [entry.public_ref for entry in report.waited_too_long()]
    assert matched == ["YOK-1"]

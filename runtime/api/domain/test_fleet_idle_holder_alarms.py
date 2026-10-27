"""Idle-holder alarms: declared waits, blocked dependents, repeat and clear."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from yoke_core.domain.fleet_delta_alarms import (
    DeltaState,
    IDLE_HOLDER_MINUTES,
    IDLE_HOLDER_REPEAT_MINUTES,
    idle_holder_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import (
    SESSIONS_FUNCTION,
    FleetSnapshot,
    item_rows,
    SessionRow,
    read_snapshot,
    session_rows,
)

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
STALE = NOW - timedelta(minutes=IDLE_HOLDER_MINUTES + 1)


def _session(session_id: str, **overrides) -> SessionRow:
    fields = {
        "session_id": session_id,
        "executor_surface": "claude-cli",
        "mode": "dash",
        "parked": False,
        "ended": False,
        "terminated": False,
        "activity_at": STALE,
        "claimed_items": ("YOK-1",),
        "message_delivery": "mid-turn — message arrives at its next tool call",
    }
    fields.update(overrides)
    return SessionRow(**fields)


def _snapshot(*rows: SessionRow, at: datetime = NOW, **overrides) -> FleetSnapshot:
    return FleetSnapshot(
        taken_at=at,
        self_session_id="steerer",
        sessions={row.session_id: row for row in rows},
        **overrides,
    )


def test_idle_holder_fires_past_threshold_and_holds_inside_the_cadence() -> None:
    state = DeltaState()
    first = idle_holder_alarms(_snapshot(_session("a")), state)
    assert len(first) == 1
    assert "ALARM idle-holder session=a items=YOK-1 idle=21m mode=dash" in first[0]
    assert "process=" not in first[0]

    later = NOW + timedelta(minutes=IDLE_HOLDER_REPEAT_MINUTES - 1)
    assert idle_holder_alarms(_snapshot(_session("a"), at=later), state) == []


def test_parked_holder_past_threshold_alarms_with_its_reason() -> None:
    parked = _session(
        "p", mode="parked", parked=True, quiet_reason="waiting on YOK-3965"
    )
    [line] = idle_holder_alarms(_snapshot(parked), DeltaState())
    assert "session=p" in line
    assert "mode=parked reason='waiting on YOK-3965'" in line


def test_parked_holder_alarms_once_rather_than_on_the_cadence() -> None:
    state = DeltaState()
    parked = _session("p", mode="parked", parked=True)
    assert len(idle_holder_alarms(_snapshot(parked), state)) == 1

    later = NOW + timedelta(minutes=3 * IDLE_HOLDER_REPEAT_MINUTES)
    assert idle_holder_alarms(_snapshot(parked, at=later), state) == []


def test_between_turns_holder_alarms_with_message_wake() -> None:
    gone = _session("g", message_delivery="between turns — message wakes it")
    [line] = idle_holder_alarms(_snapshot(gone), DeltaState())
    assert "delivery='between turns — message wakes it'" in line


def test_still_idle_holder_reraises_after_the_cadence() -> None:
    state = DeltaState()
    idle_holder_alarms(_snapshot(_session("a")), state)
    later = NOW + timedelta(minutes=IDLE_HOLDER_REPEAT_MINUTES)
    [again] = idle_holder_alarms(_snapshot(_session("a"), at=later), state)
    assert "ALARM idle-holder session=a" in again
    assert f"idle={IDLE_HOLDER_MINUTES + 1 + IDLE_HOLDER_REPEAT_MINUTES}m" in again


def test_idle_holder_clears_once_when_activity_resumes() -> None:
    state = DeltaState()
    idle_holder_alarms(_snapshot(_session("a", mode="parked", parked=True)), state)

    active = _session("a", activity_at=NOW)
    assert idle_holder_alarms(_snapshot(active), state) == [
        "fleet CLEAR idle-holder session=a"
    ]
    assert idle_holder_alarms(_snapshot(active), state) == []
    assert state.raised_at == {}


def test_fresh_unclaimed_and_landing_holders_stay_quiet() -> None:
    snapshot = _snapshot(
        _session("fresh", activity_at=NOW),
        _session("unclaimed", claimed_items=()),
        _session("landing", claimed_items=("YOK-7",)),
        landing_waits=frozenset({"YOK-7"}),
    )
    assert idle_holder_alarms(snapshot, DeltaState()) == []


def test_older_roster_does_not_invent_delivery_state() -> None:
    row = session_rows({"rows": [{"session_id": "old"}]})["old"]
    assert row.message_delivery == "delivery state unknown — inspect session evidence"


def test_session_rows_carry_park_reason_and_delivery() -> None:
    rows = session_rows(
        {
            "rows": [
                {
                    "session_id": "p",
                    "mode": "parked",
                    "quiet_reason": "awaiting operator",
                    "message_delivery": "parked awaiting operator",
                    "claims": [{"target_kind": "item", "target": "YOK-1"}],
                }
            ]
        }
    )
    row = rows["p"]
    assert row.parked and row.quiet_reason == "awaiting operator"
    assert row.message_delivery == "parked awaiting operator"
    assert row.claimed_items == ("YOK-1",)


def test_probe_reads_the_full_live_roster_rather_than_the_summary_page() -> None:
    payloads = {}

    def call(function, payload):
        payloads[function] = payload
        return SimpleNamespace(success=True, result={})

    read_snapshot(["yoke"], call=call, now=NOW, self_session_id="seat")
    assert payloads[SESSIONS_FUNCTION] == {
        "project": "yoke",
        "open": True,
        "detail": "full",
    }


def test_parked_holder_repeats_while_named_dependents_wait() -> None:
    from dataclasses import replace

    blocker, dependent = (f"WORK-{number}" for number in (1, 2))
    parked = _session("p", mode="parked", parked=True, claimed_items=(blocker,))
    items = item_rows({"blocked_steps": [
        {"item_id": dependent, "blocked_by": [blocker]},
    ]})
    state = DeltaState()
    snapshot = _snapshot(parked, items=items)
    assert f"dependents={dependent}" in idle_holder_alarms(snapshot, state)[0]
    inside = replace(snapshot, taken_at=NOW + timedelta(minutes=59))
    assert idle_holder_alarms(inside, state) == []
    later = replace(snapshot, taken_at=NOW + timedelta(minutes=60))
    assert f"dependents={dependent}" in idle_holder_alarms(later, state)[0]
    cleared = replace(later, taken_at=NOW + timedelta(minutes=120), items={})
    assert idle_holder_alarms(cleared, state) == []

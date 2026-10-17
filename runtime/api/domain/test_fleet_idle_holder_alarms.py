"""Idle-holder alarms: parked holders, process state, repeat cadence, clear."""

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
    SessionRow,
    process_state,
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
        "process": "running",
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
    assert "mode=dash reason=none process=running" in first[0]

    later = NOW + timedelta(minutes=IDLE_HOLDER_REPEAT_MINUTES - 1)
    assert idle_holder_alarms(_snapshot(_session("a"), at=later), state) == []


def test_parked_holder_past_threshold_alarms_with_its_reason() -> None:
    parked = _session(
        "p", mode="parked", parked=True, quiet_reason="waiting on YOK-3965"
    )
    [line] = idle_holder_alarms(_snapshot(parked), DeltaState())
    assert "session=p" in line
    assert "mode=parked reason='waiting on YOK-3965'" in line


def test_exited_process_holder_alarms_with_process_exited() -> None:
    gone = _session("g", mode="parked", parked=True, process="exited")
    [line] = idle_holder_alarms(_snapshot(gone), DeltaState())
    assert "process=exited" in line


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


def test_process_state_reads_hidden_clean_exit_and_older_rosters() -> None:
    assert (
        process_state({"native_process": None, "native_process_exited_at": None})
        == "running"
    )
    assert (
        process_state({"native_process": None, "native_process_exited_at": "t"})
        == "exited"
    )
    assert process_state({"native_process": {"state": "gone"}}) == "exited"
    assert process_state({"native_process": {"state": "resuming"}}) == "resuming"
    assert process_state({"native_process": None}) == "unknown"


def test_session_rows_carry_park_reason_and_process() -> None:
    rows = session_rows(
        {
            "rows": [
                {
                    "session_id": "p",
                    "mode": "parked",
                    "quiet_reason": "awaiting operator",
                    "native_process": None,
                    "native_process_exited_at": "2026-08-28T16:00:00Z",
                    "claims": [{"target_kind": "item", "target": "YOK-1"}],
                }
            ]
        }
    )
    row = rows["p"]
    assert row.parked and row.quiet_reason == "awaiting operator"
    assert row.process == "exited" and row.claimed_items == ("YOK-1",)


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

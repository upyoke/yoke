"""Change detection between two fleet observations."""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_lines import (
    compare,
    error_line,
    fatal_line,
    item_deltas,
    session_deltas,
)
from yoke_core.domain.fleet_delta_snapshot import (
    FleetSnapshot,
    ItemRow,
    SessionRow,
)

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)
STEERER = "steerer-0000"


def _snapshot(**overrides) -> FleetSnapshot:
    fields = {
        "taken_at": NOW,
        "self_session_id": STEERER,
        "sessions": {},
        "items": {},
        "envelopes": {},
    }
    fields.update(overrides)
    return FleetSnapshot(**fields)


def _item(ref: str, status: str, claim_state: str = "unclaimed") -> ItemRow:
    return ItemRow(
        ref=ref,
        status=status,
        title="t",
        claim_state=claim_state,
        project="yoke",
    )


def _session(session_id: str, **overrides) -> SessionRow:
    fields = {
        "session_id": session_id,
        "executor_surface": "codex-cli",
        "mode": "dash",
        "parked": False,
        "ended": False,
        "terminated": False,
        "activity_at": NOW,
        "claimed_items": (),
    }
    fields.update(overrides)
    return SessionRow(**fields)


def test_an_unchanged_fleet_emits_nothing() -> None:
    snapshot = _snapshot(
        items={"YOK-1": _item("YOK-1", "implementing", "claimed_by_self")},
        sessions={"a": _session("a")},
    )
    assert compare(snapshot, snapshot, DeltaState()) == []


def test_the_arming_pass_emits_no_item_or_session_deltas() -> None:
    """With no previous observation there is nothing to compare against."""
    snapshot = _snapshot(
        items={"YOK-1": _item("YOK-1", "implementing")},
        sessions={"a": _session("a")},
    )
    assert compare(None, snapshot, DeltaState()) == []


def test_item_status_and_claim_changes_each_emit_one_line() -> None:
    before = _snapshot(items={"YOK-1": _item("YOK-1", "idea")})
    after = _snapshot(
        items={"YOK-1": _item("YOK-1", "implementing", "claimed_by_other_live")}
    )
    lines = item_deltas(before, after)
    assert lines == [
        "fleet item YOK-1 status idea -> implementing",
        "fleet item YOK-1 claim unclaimed -> claimed_by_other_live",
    ]


def test_items_entering_and_leaving_the_frontier_are_reported() -> None:
    before = _snapshot(items={"YOK-1": _item("YOK-1", "reviewing-implementation")})
    after = _snapshot(items={"YOK-2": _item("YOK-2", "idea")})
    lines = item_deltas(before, after)
    assert "fleet item YOK-2 entered status=idea claim=unclaimed" in lines
    assert (
        "fleet item YOK-1 left-frontier last-status=reviewing-implementation" in lines
    )


def test_session_registration_and_ending_are_reported_once() -> None:
    before = _snapshot()
    after = _snapshot(sessions={"a": _session("a")})
    assert session_deltas(before, after) == [
        "fleet session a registered surface=codex-cli mode=dash"
    ]

    ended = _snapshot(sessions={"a": _session("a", ended=True)})
    assert session_deltas(after, ended) == ["fleet session a ended surface=codex-cli"]
    assert session_deltas(ended, ended) == []


def test_a_terminated_session_reports_termination_not_ending() -> None:
    before = _snapshot(sessions={"a": _session("a")})
    after = _snapshot(sessions={"a": _session("a", ended=True, terminated=True)})
    assert session_deltas(before, after) == [
        "fleet session a terminated surface=codex-cli"
    ]


def test_read_failure_lines_name_the_function_and_the_recovery() -> None:
    transient = error_line("sessions.list", "https_transport_failed", 1, 3)
    assert "fleet ERROR read failed sessions.list" in transient
    assert "attempt 1/3" in transient

    terminal = fatal_line("charge.schedule", "unreachable", 3)
    assert "fleet FATAL read failed charge.schedule" in terminal
    assert "yoke env list" in terminal
    assert "yoke watch fleet" in terminal

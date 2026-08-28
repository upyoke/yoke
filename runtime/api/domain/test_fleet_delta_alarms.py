"""Negative-space alarm detectors: thresholds, dedupe, and exclusions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.fleet_delta_alarms import (
    DeltaState,
    IDLE_HOLDER_MINUTES,
    STARVED_ENVELOPE_MINUTES,
    UNOWNED_ITEM_MINUTES,
    idle_holder_alarms,
    inbox_lines,
    starved_envelope_alarms,
    unowned_item_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import (
    EnvelopeRow,
    FleetSnapshot,
    ItemRow,
    SessionRow,
)

NOW = datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc)


def _session(session_id: str, **overrides) -> SessionRow:
    fields = {
        "session_id": session_id,
        "executor_surface": "claude-cli",
        "mode": "dash",
        "parked": False,
        "ended": False,
        "terminated": False,
        "activity_at": NOW,
        "claimed_items": ("YOK-1",),
    }
    fields.update(overrides)
    return SessionRow(**fields)


def _snapshot(**overrides) -> FleetSnapshot:
    fields = {
        "taken_at": NOW,
        "self_session_id": "steerer-0000",
        "sessions": {},
        "items": {},
        "envelopes": {},
    }
    fields.update(overrides)
    return FleetSnapshot(**fields)


def _item(ref: str, **overrides) -> ItemRow:
    fields = {
        "ref": ref,
        "status": "implementing",
        "title": "t",
        "claim_state": "unclaimed",
        "project": "yoke",
    }
    fields.update(overrides)
    return ItemRow(**fields)


def test_idle_holder_fires_past_threshold_and_dedupes() -> None:
    stale = NOW - timedelta(minutes=IDLE_HOLDER_MINUTES + 1)
    snapshot = _snapshot(sessions={"a": _session("a", activity_at=stale)})
    state = DeltaState()

    first = idle_holder_alarms(snapshot, state)
    assert len(first) == 1
    assert "ALARM idle-holder" in first[0]
    assert "items=YOK-1" in first[0]

    assert idle_holder_alarms(snapshot, state) == []


def test_idle_holder_ignores_parked_and_fresh_holders() -> None:
    stale = NOW - timedelta(minutes=IDLE_HOLDER_MINUTES + 1)
    snapshot = _snapshot(
        sessions={
            "parked": _session("parked", activity_at=stale, parked=True),
            "fresh": _session("fresh"),
            "unclaimed": _session("unclaimed", activity_at=stale, claimed_items=()),
        }
    )
    assert idle_holder_alarms(snapshot, DeltaState()) == []


def test_idle_holder_clears_once_when_the_holder_returns() -> None:
    stale = NOW - timedelta(minutes=IDLE_HOLDER_MINUTES + 1)
    state = DeltaState()
    idle_holder_alarms(
        _snapshot(sessions={"a": _session("a", activity_at=stale)}), state
    )

    cleared = idle_holder_alarms(_snapshot(sessions={"a": _session("a")}), state)
    assert cleared == ["fleet CLEAR idle-holder session=a"]
    assert idle_holder_alarms(_snapshot(sessions={"a": _session("a")}), state) == []


def test_unowned_item_requires_continuous_absence_not_a_snapshot() -> None:
    """A momentary claim gap at a segment boundary must not alarm."""
    state = DeltaState()
    first = _snapshot(items={"YOK-9": _item("YOK-9")})
    assert unowned_item_alarms(first, state) == []

    later = _snapshot(
        taken_at=NOW + timedelta(minutes=UNOWNED_ITEM_MINUTES + 1),
        items={"YOK-9": _item("YOK-9")},
    )
    fired = unowned_item_alarms(later, state)
    assert len(fired) == 1
    assert "ALARM unowned-item YOK-9" in fired[0]


def test_unowned_item_ignores_backlog_ideas_and_claimed_items() -> None:
    state = DeltaState()
    snapshot = _snapshot(
        items={
            "YOK-1": _item("YOK-1", status="idea"),
            "YOK-2": _item("YOK-2", claim_state="claimed_by_other_live"),
        }
    )
    unowned_item_alarms(snapshot, state)
    later = _snapshot(
        taken_at=NOW + timedelta(minutes=UNOWNED_ITEM_MINUTES + 1),
        items=snapshot.items,
    )
    assert unowned_item_alarms(later, state) == []


def _envelope(**overrides) -> EnvelopeRow:
    fields = {
        "message_id": "msg-1111",
        "recipient_session_id": "a",
        "sender_session_id": "steerer-0000",
        "state": "pending",
        "injection_count": 0,
        "created_at": NOW - timedelta(minutes=STARVED_ENVELOPE_MINUTES + 1),
    }
    fields.update(overrides)
    return EnvelopeRow(**fields)


def test_starved_envelope_fires_for_a_quiet_live_recipient() -> None:
    row = _envelope()
    snapshot = _snapshot(
        sessions={
            "a": _session("a", activity_at=NOW - timedelta(hours=2), claimed_items=())
        },
        envelopes={row.key: row},
    )
    fired = starved_envelope_alarms(snapshot, DeltaState())
    assert len(fired) == 1
    assert "ALARM starved-envelope" in fired[0]
    assert "recipient=a" in fired[0]


def test_starved_envelope_excludes_recipients_whose_session_ended() -> None:
    """The pending-forever envelope that re-fires on every pass."""
    row = _envelope()
    snapshot = _snapshot(
        sessions={
            "a": _session(
                "a",
                ended=True,
                activity_at=NOW - timedelta(hours=2),
                claimed_items=(),
            )
        },
        envelopes={row.key: row},
    )
    assert starved_envelope_alarms(snapshot, DeltaState()) == []


def test_starved_envelope_excludes_a_recipient_that_acted_since_the_send() -> None:
    row = _envelope()
    snapshot = _snapshot(
        sessions={"a": _session("a", activity_at=NOW, claimed_items=())},
        envelopes={row.key: row},
    )
    assert starved_envelope_alarms(snapshot, DeltaState()) == []


def test_starved_envelope_ignores_injected_and_recent_envelopes() -> None:
    injected = _envelope(message_id="msg-2222", injection_count=3)
    recent = _envelope(message_id="msg-3333", created_at=NOW)
    snapshot = _snapshot(
        sessions={
            "a": _session("a", activity_at=NOW - timedelta(hours=2), claimed_items=())
        },
        envelopes={injected.key: injected, recent.key: recent},
    )
    assert starved_envelope_alarms(snapshot, DeltaState()) == []


def _inbox(message_id: str, state: str, recipient: str) -> EnvelopeRow:
    return EnvelopeRow(
        message_id=message_id,
        recipient_session_id=recipient,
        sender_session_id="worker-9999",
        state=state,
        injection_count=1,
        created_at=NOW,
    )


def test_inbox_fires_on_the_arming_pass_for_an_envelope_already_waiting() -> None:
    """Unread is a level: the first thing a steerer needs told on arming."""
    waiting = _inbox("msg-1111", "pending", "steerer-0000")
    snapshot = _snapshot(envelopes={waiting.key: waiting})
    state = DeltaState()

    assert inbox_lines(snapshot, state) == [
        "fleet inbox msg-1111 state=pending from=worker-9"
    ]
    assert inbox_lines(snapshot, state) == [], "a level fires once, not per pass"


def test_inbox_ignores_envelopes_for_other_sessions_and_acknowledged_ones() -> None:
    theirs = _inbox("msg-2222", "pending", "someone-else")
    done = _inbox("msg-3333", "acknowledged", "steerer-0000")
    snapshot = _snapshot(envelopes={theirs.key: theirs, done.key: done})
    assert inbox_lines(snapshot, DeltaState()) == []


def test_inbox_reports_a_state_change_and_stays_silent_on_acknowledgement() -> None:
    state = DeltaState()
    pending = _inbox("msg-1111", "pending", "steerer-0000")
    inbox_lines(_snapshot(envelopes={pending.key: pending}), state)

    injected = _inbox("msg-1111", "injected", "steerer-0000")
    assert inbox_lines(_snapshot(envelopes={injected.key: injected}), state) == [
        "fleet inbox msg-1111 state=injected from=worker-9"
    ]

    done = _inbox("msg-1111", "acknowledged", "steerer-0000")
    assert inbox_lines(_snapshot(envelopes={done.key: done}), state) == []
    assert not any(key.startswith("inbox:") for key in state.active_alarms)

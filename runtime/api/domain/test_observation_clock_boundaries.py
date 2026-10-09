"""Hook wire clocks and native attribution windows preserve microseconds."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import observe_event_emission, observe_normalization, observe_pre
from yoke_core.domain.observe_parsing import EventRecord

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")
WIRE = "1969-12-31T23:59:59.123456Z"


def test_start_and_completion_read_one_clock_with_full_precision(monkeypatch):
    def clock():
        clock.calls += 1
        return STAMP + timedelta(seconds=clock.calls - 1)

    clock.calls = 0
    monkeypatch.setattr(observe_pre, "utc_now", clock)
    started = observe_pre.parse_pre_event({"tool_use_id": "native-start"})
    assert started["event_time"] == WIRE
    assert clock.calls == 1
    clock.calls = 0
    monkeypatch.setattr(observe_event_emission, "utc_now", clock)
    completed = observe_event_emission.build_envelope(EventRecord(exit_code=0))
    assert completed["event_time"] == WIRE
    assert clock.calls == 1


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_event_sql_retains_native_clock_beside_canonical_envelope(
    test_db, monkeypatch, zone
):
    import json

    monkeypatch.setattr(observe_pre, "utc_now", lambda: STAMP)
    monkeypatch.setattr(
        observe_event_emission, "resolve_envelope_project_id_for_event", lambda *_: 1
    )
    monkeypatch.setattr(
        observe_event_emission, "_apply_state_and_commit", lambda conn, _: conn.commit()
    )
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    envelope = observe_pre.parse_pre_event({"tool_use_id": "native-event"})
    observe_event_emission.insert_event(test_db, envelope)
    row = test_db.execute(
        "SELECT created_at, envelope FROM events WHERE event_id=%s",
        (envelope["event_id"],),
    ).fetchone()
    assert row[0] == STAMP
    payload = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    assert payload["event_time"] == WIRE


@pytest.mark.parametrize(
    "age, expected",
    [
        (timedelta(0), ("7", "session_recent")),
        (timedelta(minutes=30), ("7", "session_recent")),
        (timedelta(minutes=30, microseconds=1), (None, None)),
        (timedelta(microseconds=-1), (None, None)),
    ],
)
def test_recent_attribution_checks_exact_native_window(
    monkeypatch, tmp_path, age, expected
):
    conn = SimpleNamespace(
        execute=lambda *_: SimpleNamespace(
            fetchone=lambda: (None, 7, STAMP), fetchall=lambda: []
        ),
        close=lambda: None,
    )
    monkeypatch.setattr(
        observe_normalization, "connect_observe_read_db", lambda _: conn
    )
    monkeypatch.setattr(
        observe_normalization, "repo_root_for_attribution", lambda *_: str(tmp_path)
    )
    monkeypatch.setattr(observe_normalization, "_item_exists", lambda *_: True)
    monkeypatch.setattr(observe_normalization, "utc_now", lambda: STAMP + age)
    assert (
        observe_normalization._resolve_main_session_attribution(
            "disposable", str(tmp_path), "session"
        )
        == expected
    )

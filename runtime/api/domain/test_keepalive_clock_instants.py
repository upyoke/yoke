"""Keepalive persistence and inclusive expiry retain exact native instants."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import session_keepalive as keepalive
from runtime.api.domain.coordination_claim_test_support import seed_session

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_keepalive_sql_native_microseconds_and_wire_facts_then_null_release(
    test_db, zone
):
    seed_session(test_db, "clock-hold")
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    until = MOMENT + timedelta(seconds=60)
    row = keepalive.hold_session_keepalive(
        test_db, "clock-hold", seconds=60, reason="native clock", now=MOMENT
    )
    assert (
        isinstance(row["keepalive_until"], datetime) and row["keepalive_until"] == until
    )
    before = until - timedelta(microseconds=1)
    facts = keepalive.session_keepalive_holds(test_db, ["clock-hold"], now=before)
    assert facts["clock-hold"]["keepalive_until"] == format_instant(until)
    assert keepalive.session_keepalive_holds(test_db, ["clock-hold"], now=until) == {}
    assert (
        keepalive.session_keepalive_holds(
            test_db, ["clock-hold"], now=until + timedelta(microseconds=1)
        )
        == {}
    )
    assert keepalive.release_session_keepalive(test_db, "clock-hold")
    assert (
        test_db.execute(
            "SELECT keepalive_until FROM harness_sessions WHERE session_id='clock-hold'"
        ).fetchone()[0]
        is None
    )


@pytest.mark.parametrize("delta,held", [(-1, True), (0, False), (1, False)])
@pytest.mark.parametrize("offset", [0, 9, -4])
def test_keepalive_exact_expiry_is_offset_independent(delta, held, offset):
    zone = timezone(timedelta(hours=offset))
    row = {"keepalive_until": MOMENT.astimezone(zone), "keepalive_reason": "live"}
    facts = keepalive.session_keepalive_facts(
        row, now=(MOMENT + timedelta(microseconds=delta)).astimezone(zone)
    )
    assert bool(facts) is held
    if held:
        assert facts["keepalive_until"] == format_instant(MOMENT)


@pytest.mark.parametrize(
    "value", ["", "2026-10-09", "2026-10-09T10:26:12", MOMENT.replace(tzinfo=None)]
)
def test_invalid_current_keepalive_clock_refuses_before_update(test_db, value):
    seed_session(test_db, "clock-hold")
    with pytest.raises(InvalidInstant):
        keepalive.hold_session_keepalive(
            test_db, "clock-hold", seconds=60, reason="clock", now=value
        )
    assert (
        test_db.execute(
            "SELECT keepalive_until,keepalive_reason FROM harness_sessions WHERE session_id='clock-hold'"
        ).fetchone()[0]
        is None
    )


def test_default_keepalive_generator_is_native_and_rejects_naive(test_db, monkeypatch):
    seed_session(test_db, "clock-hold")
    monkeypatch.setattr(keepalive, "utc_now", lambda: MOMENT)
    expected = MOMENT + timedelta(seconds=60)
    assert (
        keepalive.hold_session_keepalive(
            test_db, "clock-hold", seconds=60, reason="clock"
        )["keepalive_until"]
        == expected
    )
    monkeypatch.setattr(keepalive, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(InvalidInstant):
        keepalive.hold_session_keepalive(
            test_db, "clock-hold", seconds=120, reason="bad clock"
        )
    assert (
        test_db.execute(
            "SELECT keepalive_until FROM harness_sessions WHERE session_id='clock-hold'"
        ).fetchone()[0]
        == expected
    )

"""Fleet clocks retain native instants through reads, intervals and projections."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.delivery_landing_custody import landed_at
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_plan_capacity import (
    format_reset_utc,
    time_until_reset,
)
from yoke_core.domain.steering_fleet_report import compose_report
from yoke_core.domain.steering_fleet_report_delivery import (
    _claim_interval,
    _last_report,
    record_report_delivery,
    steering_report_candidate,
)
from yoke_core.domain.steering_fleet_report_detectors import age_seconds
from yoke_core.domain.steering_fleet_report_in_flight import (
    in_flight_calls,
    in_flight_dicts,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.work_claim_targets import make_item_target

START = "1969-12-31T23:59:59.123456Z"
OFFSET_NOW = "1969-12-31T19:00:00.123456-05:00"
CANONICAL_NOW = "1970-01-01T00:00:00.123456Z"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_native_fleet_rows_and_projections_agree_in_every_session_zone(test_db, zone):
    from runtime.api.steering_fleet_test_helpers import (
        WORKER_SESSION,
        compose,
        seed_steering_scope,
        seed_tool_call,
    )

    conn = seed_steering_scope(test_db)
    conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    start, now = parse_instant(START), parse_instant(OFFSET_NOW)
    conn.execute("UPDATE items SET created_at=%s,updated_at=%s", (start, start))
    conn.execute(
        "UPDATE harness_sessions SET offered_at=%s,last_heartbeat=%s,last_tool_call_at=%s",
        (start, now, start),
    )
    conn.execute(
        "UPDATE session_relays SET connected_until=%s,last_seen_at=%s",
        (now + timedelta(days=1), now),
    )
    conn.commit()
    report = compose(conn, now=OFFSET_NOW)
    assert report.composed_at == now
    assert all(entry.pickable_since == start for entry in report.available)
    wire = report_dict(report)
    assert wire["composed_at"] == CANONICAL_NOW
    assert all(entry["pickable_since"] == START for entry in wire["available"])
    assert all(entry["launched_at"] is None for entry in wire["available"])
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    conn.execute(
        "UPDATE work_claims SET claimed_at=%s WHERE session_id=%s",
        (start, WORKER_SESSION),
    )
    seed_tool_call(
        conn,
        WORKER_SESSION,
        tool_use_id="running-call",
        started_at=start,
        command_summary="yoke watch pytest -- selection",
    )
    conn.commit()
    report = compose(conn, now=now)
    holder = next(row for row in report.holders if row.session_id == WORKER_SESSION)
    assert holder.last_activity_at == start
    assert holder.native_process_gone_at is holder.resume_started_at is None
    calls = in_flight_calls(conn, quiet=[holder], now=now)
    assert len(calls) == 1
    assert calls[0].started_at == start
    assert calls[0].open_seconds == 1
    assert in_flight_dicts(calls)[0]["started_at"] == START


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_report_interval_preserves_the_inclusive_microsecond_cutoff(test_db, zone):
    from runtime.api.steering_fleet_test_helpers import (
        STEERING_SESSION,
        seed_steering_scope,
    )

    conn = seed_steering_scope(test_db)
    conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    start = parse_instant(START)
    args = {"session_id": STEERING_SESSION, "fingerprint": "opaque fingerprint"}
    assert _claim_interval(conn, now=start, not_after=start, **args)
    assert _last_report(conn, STEERING_SESSION)[0] == start
    later = start + timedelta(minutes=15)
    assert not _claim_interval(
        conn, now=later, not_after=start - timedelta(microseconds=1), **args
    )
    assert _claim_interval(conn, now=later, not_after=start, **args)
    assert _last_report(conn, STEERING_SESSION)[0] == later


def test_landing_selection_compares_exact_instants_and_keeps_absence_null():
    earlier = "1970-01-01T01:59:59.123455+02:00"
    assert landed_at(
        {"merged_at": START, "merge_queue_landed_at": earlier}
    ) == parse_instant(earlier)
    assert landed_at({"merged_at": None, "merge_queue_landed_at": None}) is None
    assert age_seconds(START, OFFSET_NOW) == 1
    assert age_seconds(None, OFFSET_NOW) is None
    assert time_until_reset(START, OFFSET_NOW) == -timedelta(seconds=1)


def test_plan_reset_record_is_native_and_its_calendar_label_is_utc():
    row = MachinePlanLimit(
        machine_id="machine",
        machine_name="box",
        surface="cursor-cli",
        plan_tier=None,
        window_kind="rolling_5h",
        scope="all",
        meter="opaque",
        remaining_percent=0,
        resets_at=OFFSET_NOW,
        status="ok",
        reason=None,
    )
    assert row.resets_at == parse_instant(CANONICAL_NOW)
    assert format_reset_utc(row.resets_at) == "Jan 1 00:00"
    assert format_reset_utc(None) == "-"


class NoSQL:
    def execute(self, *_args):
        raise AssertionError("malformed clock reached SQL")


@pytest.mark.parametrize("bad", ["", "2026-09-03", "2026-09-03T12:00:00", 0, False])
def test_supplied_invalid_fleet_clocks_refuse_before_any_read_or_write(bad):
    conn = NoSQL()
    with pytest.raises(InvalidInstant):
        steering_report_candidate(conn, session_id="session", now=bad)
    with pytest.raises(InvalidInstant):
        record_report_delivery(
            conn, session_id="session", fingerprint="opaque", now=bad
        )
    with pytest.raises(InvalidInstant):
        compose_report(
            conn,
            project_id=1,
            session_id="session",
            staffing_after_seconds=1,
            idle_after_seconds=1,
            now=bad,
        )
    with pytest.raises(InvalidInstant):
        _claim_interval(
            conn,
            session_id="session",
            fingerprint="opaque",
            now=bad,
            not_after=parse_instant(START),
        )
    with pytest.raises(InvalidInstant):
        time_until_reset(bad, OFFSET_NOW)
    with pytest.raises(InvalidInstant):
        format_reset_utc(bad)
    with pytest.raises(InvalidInstant):
        landed_at({"merged_at": bad})

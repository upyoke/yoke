"""Item window projections and recovery readers retain native microseconds."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import item_finished_times
from yoke_core.domain.chain_head_freshness import _age_seconds
from yoke_core.domain.frontier_recent_owner import _parse_iso
from yoke_core.domain.item_execution_status_helpers import (
    age_seconds,
    collect_latest_transition,
)
from yoke_core.domain.sessions_lifecycle_reactivation_claims import _within_window


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_finished_window_binds_exact_native_cutoff_and_formats_view(
    test_db, monkeypatch, zone
):
    from runtime.api.fixtures.backlog import insert_item

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    cutoff = parse_instant("1969-12-31T23:59:59.999999Z")
    now = cutoff + timedelta(seconds=1)
    monkeypatch.setattr(item_finished_times, "utc_now", lambda: now)
    expected = {}
    for item_id, micros in enumerate([-1, 0, 1], start=101):
        instant = cutoff + timedelta(microseconds=micros)
        insert_item(
            test_db,
            id=item_id,
            title="Native window",
            status="implementing",
            created_at=instant,
            updated_at=instant,
        )
        test_db.execute(
            "INSERT INTO item_status_transitions(item_id,to_status,source,created_at) "
            "VALUES(%s,'implementing','test',%s)",
            (item_id, instant),
        )
        if micros >= 0:
            expected[item_id] = format_instant(instant)
        if micros == 1:
            view = collect_latest_transition(test_db, item_id, now=now)
            assert view["latest_at"] == format_instant(instant)
            assert view["latest_age_seconds"] == 0
    test_db.commit()
    assert item_finished_times.window_cutoff(timedelta(seconds=1)) == cutoff
    result = item_finished_times.finished_times_in_window(test_db, timedelta(seconds=1))
    assert {
        key: value for key, value in result.items() if key in [101, 102, 103]
    } == expected


def test_recovery_readers_preserve_exact_inclusive_release_boundary():
    now = parse_instant("1969-12-31T23:59:59.999999Z")
    boundary = now - timedelta(seconds=300)
    assert _within_window(boundary, 300, now=now)
    assert not _within_window(boundary - timedelta(microseconds=1), 300, now=now)
    assert not _within_window(now + timedelta(microseconds=1), 300, now=now)
    assert not _within_window(None, 300, now=now)
    assert _parse_iso(now) == now
    assert _parse_iso(None) is None
    assert _age_seconds(boundary + timedelta(microseconds=1), now) == 299
    assert age_seconds(now + timedelta(microseconds=1), now=now) == 0


@pytest.mark.parametrize(
    "bad", ["", "1969-12-31", "1969-12-31T23:59:59", datetime(1969, 12, 31)]
)
def test_bad_activity_cannot_imply_stale_or_resumable(bad):
    now = parse_instant("1969-12-31T23:59:59.999999Z")
    for operation in [
        lambda: _parse_iso(bad),
        lambda: _age_seconds(bad, now),
        lambda: age_seconds(bad, now=now),
        lambda: _within_window(bad, 300, now=now),
    ]:
        with pytest.raises(InvalidInstant, match="invalid_instant"):
            operation()

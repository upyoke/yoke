"""Path and Pack freshness clocks preserve native microseconds."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import pack_projection, path_claim_ambient_siblings

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


def test_pack_report_freshness_includes_the_exact_native_boundary(monkeypatch):
    monkeypatch.setattr(pack_projection, "utc_now", lambda: STAMP)
    floor = STAMP - pack_projection.PACK_REPORT_FRESHNESS
    assert pack_projection._report_is_fresh(floor)
    assert not pack_projection._report_is_fresh(floor - timedelta(microseconds=1))
    assert not pack_projection._report_is_fresh(None)


def test_path_claim_age_keeps_native_database_facts(monkeypatch):
    monkeypatch.setattr(path_claim_ambient_siblings, "utc_now", lambda: STAMP)
    assert path_claim_ambient_siblings._age_hours(STAMP - timedelta(hours=24)) == 24
    assert (
        path_claim_ambient_siblings._age_hours(
            STAMP - timedelta(hours=24, microseconds=1)
        )
        > 24
    )


@pytest.mark.parametrize("clock", ["", "2026-10-09 03:00:00", datetime(2026, 10, 9), 1])
def test_malformed_internal_path_and_pack_clocks_refuse(clock):
    with pytest.raises(ValueError):
        pack_projection._report_is_fresh(clock)
    with pytest.raises(ValueError):
        path_claim_ambient_siblings._age_hours(clock)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_planned_path_clocks_bind_native_precision(test_db, monkeypatch, zone):
    from yoke_core.domain import path_targets_planning
    from yoke_core.domain.path_registry import KIND_FILE

    monkeypatch.setattr(path_targets_planning, "_utc_now_iso", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    target = path_targets_planning.plan_path_target(
        test_db, project_id=1, path_string="native-clock/file.py", kind=KIND_FILE
    )
    row = test_db.execute(
        "SELECT created_at, materialization_updated_at FROM path_targets WHERE id=%s",
        (target,),
    ).fetchone()
    assert tuple(row) == (STAMP, STAMP)

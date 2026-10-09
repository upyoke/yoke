"""Doctor ages use native instants, precise boundaries and honest refusals."""

from datetime import datetime, timedelta

import pytest
from yoke_contracts.timestamps import parse_instant
from yoke_core.engines import doctor_report as report
from yoke_core.engines import doctor_hc_meta as meta
from yoke_core.engines import doctor_hc_meta_backlog as backlog
from yoke_core.engines import doctor_hc_meta_runs as runs
from yoke_core.engines import doctor_hc_branch_protection as protection
from runtime.api.engines._doctor_meta_test_helpers import (
    _make_conn,
    _insert_item,
    _insert_deployment_flow,
)

EPOCH = parse_instant("1970-01-01T05:45:00+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


def result(check, conn):
    rec = report.RecordCollector()
    check(conn, report.DoctorArgs(), rec)
    assert len(rec.results) == 1
    return rec.results[0]


@pytest.mark.parametrize("zone", ZONES)
def test_blocked_age_treats_epoch_zero_as_a_valid_instant(zone, monkeypatch):
    conn = _make_conn()
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        _insert_item(conn, 41, "Blocked clock precision", blocked=1, updated_at=EPOCH)
        clock = [EPOCH + timedelta(days=31) - timedelta(microseconds=1)]
        monkeypatch.setattr(report, "utc_now", lambda: clock[0])
        assert result(meta.hc_blocked_items, conn).result == "WARN"
        clock[0] += timedelta(microseconds=1)
        outcome = result(meta.hc_blocked_items, conn)
        assert outcome.result == "FAIL"
        assert "31 days" in outcome.detail
    finally:
        conn.close()


@pytest.mark.parametrize("zone", ZONES)
def test_backlog_staleness_preserves_exact_elapsed_boundary(monkeypatch, zone):
    conn = _make_conn()
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        _insert_item(
            conn,
            41,
            "Current idea clock",
            created_at=EPOCH,
            priority="medium",
            spec="A complete documented idea.",
        )
        clock = [EPOCH + timedelta(days=30)]
        monkeypatch.setattr(report, "utc_now", lambda: clock[0])
        monkeypatch.setattr(report, "_resolve_repo_root", lambda: None)
        assert result(backlog.hc_backlog_quality, conn).result == "PASS"
        clock[0] += timedelta(microseconds=1)
        outcome = result(backlog.hc_backlog_quality, conn)
        assert outcome.result == "WARN"
        assert "stale idea" in outcome.detail
    finally:
        conn.close()


@pytest.mark.parametrize("zone", ZONES)
def test_undeployed_age_keeps_exact_inclusive_boundary(monkeypatch, zone):
    conn = _make_conn()
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        _insert_item(
            conn, 41, "Undeployed clock precision", status="done", updated_at=EPOCH
        )
        _insert_deployment_flow(conn, "clock-flow")
        conn.commit()
        clock = [EPOCH + timedelta(days=7) - timedelta(microseconds=1)]
        monkeypatch.setattr(report, "utc_now", lambda: clock[0])
        monkeypatch.setattr(report, "_read_int_cutoff", lambda _: None)
        assert result(runs.hc_undeployed_done, conn).result == "PASS"
        clock[0] += timedelta(microseconds=1)
        assert result(runs.hc_undeployed_done, conn).result == "WARN"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "bad", ["", "1970-01-01", "1970-01-01T00:00:00", "null", 0, datetime(1970, 1, 1)]
)
def test_malformed_stored_clocks_refuse_instead_of_reporting_green(monkeypatch, bad):
    monkeypatch.setattr(
        meta,
        "query_rows",
        lambda _conn, sql: (
            [{"id": 41, "updated_at": bad}]
            if "FROM items WHERE blocked" in sql
            else [
                {
                    "epic_id": 41,
                    "task_num": 1,
                    "title": "Clock task",
                    "last_heartbeat": bad,
                }
            ]
            if sql.startswith("SELECT epic_id, task_num,")
            else []
        ),
    )
    assert "invalid_instant" in result(meta.hc_blocked_items, object()).detail
    assert "invalid_instant" in result(meta.hc_dispatch_chain, object()).detail
    monkeypatch.setattr(
        backlog,
        "query_rows",
        lambda *_: [
            {
                "id": 41,
                "status": "idea",
                "created_at": bad,
                "title": "Documented clock idea",
                "priority": "medium",
                "has_body": 1,
            }
        ],
    )
    monkeypatch.setattr(backlog, "render_item_ref", lambda *_: "clock-item")
    monkeypatch.setattr(report, "_resolve_repo_root", lambda: None)
    assert "invalid_instant" in result(backlog.hc_backlog_quality, object()).detail


def test_report_and_drift_event_format_owned_clocks_with_six_digits(monkeypatch):
    monkeypatch.setattr(report, "utc_now", lambda: EPOCH)
    assert (
        "Generated: 1970-01-01T00:00:00.000000Z"
        in report.RecordCollector().format_report()
    )
    seen = []
    monkeypatch.setattr(
        protection, "iso8601_now", lambda: "1970-01-01T00:00:00.000000Z"
    )
    monkeypatch.setattr(
        protection._events, "emit_event", lambda *a, **kw: seen.append(kw)
    )
    protection._emit_drift_event(
        repo="team/repo",
        expected=[],
        actual=[],
        missing=[],
        reason="missing_required_checks",
    )
    assert seen[0]["context"]["drift_detected_at"] == "1970-01-01T00:00:00.000000Z"


@pytest.mark.parametrize("zone", ZONES)
def test_dispatch_heartbeat_keeps_exact_inclusive_boundary(monkeypatch, zone):
    conn = _make_conn()
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        _insert_item(
            conn, 41, "Epic clock precision", workflow_id="epic", status="implementing"
        )
        conn.execute(
            "INSERT INTO epic_tasks (id,epic_id,task_num,title,status,last_heartbeat) VALUES (1,41,1,'Clock task','implementing',%s)",
            (EPOCH,),
        )
        clock = [EPOCH + timedelta(hours=2) - timedelta(microseconds=1)]
        monkeypatch.setattr(report, "utc_now", lambda: clock[0])
        assert result(meta.hc_dispatch_chain, conn).result == "PASS"
        clock[0] += timedelta(microseconds=1)
        assert result(meta.hc_dispatch_chain, conn).result == "WARN"
    finally:
        conn.close()

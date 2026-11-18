"""Doctor flags a universe whose scheduled prune receipt has gone stale."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_contracts.timestamps import utc_now
from yoke_core.engines.doctor_hc_universe_prune import (
    HC_SLUG,
    hc_universe_prune_receipt,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run(conn):
    collector = RecordCollector()
    hc_universe_prune_receipt(conn, DoctorArgs(), collector)
    [result] = collector.results
    assert result.check_id == HC_SLUG
    return result


def _receipt(conn, *, age, outcome="drained", unfinished=(), failure=""):
    started = utc_now() - age
    conn.execute(
        "INSERT INTO universe_prune_receipts (started_at, completed_at, "
        "elapsed_ms, outcome, deleted, unfinished, failure_code, failure_reason) "
        "VALUES (%s, %s, 10, %s, %s, %s, %s, %s)",
        (
            started,
            started,
            outcome,
            json.dumps({"events": 4}),
            json.dumps(list(unfinished)),
            failure,
            "boom" if failure else "",
        ),
    )
    conn.commit()


def _age_universe(conn, days):
    conn.execute(
        "UPDATE organizations SET created_at = %s", (utc_now() - timedelta(days=days),)
    )
    conn.commit()


def test_recent_receipt_passes(test_db):
    _receipt(test_db, age=timedelta(hours=3))
    result = _run(test_db)
    assert result.result == "PASS" and "4 rows deleted" in result.detail


def test_receipt_older_than_two_days_fails(test_db):
    _receipt(test_db, age=timedelta(days=2, hours=1))
    result = _run(test_db)
    assert result.result == "FAIL"
    assert "more than two days ago" in result.detail
    assert "yoke universe prune --apply" in result.detail


def test_recent_failures_do_not_count_as_pruning(test_db):
    _receipt(test_db, age=timedelta(days=3))
    _receipt(
        test_db, age=timedelta(hours=1), outcome="failed", failure="retention_policy_invalid"
    )
    result = _run(test_db)
    assert result.result == "FAIL"
    assert "retention_policy_invalid: boom" in result.detail


def test_old_universe_without_receipts_fails(test_db):
    _age_universe(test_db, 5)
    result = _run(test_db)
    assert result.result == "FAIL" and "No successful" in result.detail


def test_young_universe_without_receipts_passes(test_db):
    _age_universe(test_db, 0)
    assert _run(test_db).result == "PASS"


def test_unfinished_tables_warn(test_db):
    _receipt(
        test_db,
        age=timedelta(hours=1),
        unfinished=[{"table": "events", "reason": "a lock wait hit its lock timeout"}],
    )
    result = _run(test_db)
    assert result.result == "WARN" and "events (a lock wait" in result.detail


def test_skips_before_the_table_exists(test_db):
    test_db.execute("DROP TABLE universe_prune_receipts")
    test_db.commit()
    assert _run(test_db).result == "SKIP"

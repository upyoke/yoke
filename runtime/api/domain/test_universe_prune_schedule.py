"""Control-plane upkeep runs universe pruning on a schedule and keeps receipts."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

from runtime.api.fixtures.backlog import insert_event
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_contracts.timestamps import utc_now
from yoke_contracts.universe_retention import RetentionPolicy
from yoke_core.domain import control_plane_upkeep as job
from yoke_core.domain import db_helpers
from yoke_core.domain import universe_prune_schedule as schedule
from yoke_core.domain import universe_retention as retention
from yoke_core.domain.steering_fleet_report_prune import (
    HEADING,
    failed_prune_section,
    failed_prunes,
)


def _old_events(conn, count):
    for index in range(count):
        insert_event(
            conn,
            event_id=f"old-{index}",
            severity="DEBUG",
            created_at=utc_now() - timedelta(days=2),
        )
    conn.commit()


def _old_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_id LIKE 'old-%%'"
    ).fetchone()[0]


def _receipts(conn):
    return conn.execute(
        "SELECT outcome, deleted, vacuumed, elapsed_ms, failure_code, cutoff "
        "FROM universe_prune_receipts ORDER BY id"
    ).fetchall()


def test_upkeep_runs_prune_and_writes_the_receipt(test_db, monkeypatch):
    """Upkeep's own connection runs the prune; the receipt is durable."""
    _old_events(test_db, 3)
    with connect_test_database(test_db.info.dbname) as upkeep_conn:
        monkeypatch.setattr(db_helpers, "connect", lambda: upkeep_conn)
        for name in (
            "observe_pending_github_work",
            "replay_settlement_followups",
            "wake_driverless_qa_waits",
        ):
            monkeypatch.setattr(job, name, lambda _conn: None)
        monkeypatch.setattr(upkeep_conn, "close", lambda: None, raising=False)

        job.run_control_plane_upkeep()

    assert _old_count(test_db) == 0
    [(outcome, deleted, vacuumed, elapsed_ms, failure_code, cutoff)] = _receipts(
        test_db
    )
    assert outcome == "drained"
    assert json.loads(deleted)["events"] == 3
    assert "events" in json.loads(vacuumed)
    assert elapsed_ms >= 0 and failure_code == "" and cutoff is not None


def test_drained_run_waits_for_the_cadence(test_db):
    first = schedule.run_scheduled_prune(test_db)
    assert first["ran"] and first["outcome"] == "drained"

    assert schedule.run_scheduled_prune(test_db) == {"ran": False, "reason": "not due"}

    later = utc_now() + schedule.CADENCE + timedelta(minutes=1)
    assert schedule.run_scheduled_prune(test_db, now=later)["ran"]
    assert len(_receipts(test_db)) == 2


def _policy(conn, **fields):
    retention.seed_defaults(conn)
    conn.execute(
        "UPDATE universe_settings SET value=%s WHERE key='retention'",
        (RetentionPolicy(**fields).model_dump_json(),),
    )
    conn.commit()


def test_budget_run_continues_on_the_next_cycle(test_db, monkeypatch):
    _old_events(test_db, 5)
    _policy(test_db, batch_rows=2)

    budget = schedule.run_scheduled_prune(test_db, budget=0)
    assert budget["outcome"] == "budget"
    assert json.loads(budget["vacuumed"]) == []
    assert schedule.prune_due(schedule.latest_receipt(test_db), utc_now())

    while schedule.run_scheduled_prune(test_db, budget=0)["outcome"] == "budget":
        pass
    assert _old_count(test_db) == 0
    final = schedule.latest_receipt(test_db)
    assert final.outcome == "drained"
    # The drain vacuums every table pruned since the previous drain.
    assert final.vacuumed == ["events"]
    deleted = sum(
        json.loads(row[1]).get("events", 0) for row in _receipts(test_db)
    )
    assert deleted == 5


def test_refusal_is_recorded_and_reaches_steering(test_db):
    test_db.execute(
        "INSERT INTO universe_settings (key, value, updated_at) "
        "VALUES ('retention', '{\"version\": 9}', now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )
    test_db.commit()

    result = schedule.run_scheduled_prune(test_db)

    assert result["outcome"] == "failed"
    assert result["failure_code"] == "retention_policy_invalid"
    assert "restore a valid retention document" in result["failure_reason"]
    assert result["failure_recovery"]
    [row] = failed_prunes(test_db)
    assert row.code == "retention_policy_invalid"
    lines = failed_prune_section(SimpleNamespace(failed_prunes=(row,)))
    assert lines[0] == f"{HEADING}:"
    assert "retention_policy_invalid" in lines[1]
    assert lines[2].startswith("  recovery: ")
    # A failed run is not retried until the cadence passes.
    assert not schedule.prune_due(schedule.latest_receipt(test_db), utc_now())


def test_a_later_success_clears_the_steering_section(test_db):
    test_db.execute(
        "INSERT INTO universe_settings (key, value, updated_at) "
        "VALUES ('retention', '{\"version\": 9}', now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )
    test_db.commit()
    schedule.run_scheduled_prune(test_db)
    test_db.execute("DELETE FROM universe_settings WHERE key = 'retention'")
    test_db.commit()

    later = utc_now() + schedule.CADENCE + timedelta(minutes=1)
    assert schedule.run_scheduled_prune(test_db, now=later)["outcome"] == "drained"
    assert failed_prunes(test_db) == ()


def test_another_process_holding_the_run_skips_it(test_db):
    with connect_test_database(test_db.info.dbname) as holder:
        holder.execute("SELECT pg_advisory_lock(%s)", (schedule.LOCK_KEY,))
        result = schedule.run_scheduled_prune(test_db)
        holder.execute("SELECT pg_advisory_unlock(%s)", (schedule.LOCK_KEY,))

    assert result == {"ran": False, "reason": "another process is running it"}
    assert _receipts(test_db) == []

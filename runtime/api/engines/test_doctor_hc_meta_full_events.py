"""Doctor HC tests (Events HCs + audit fingerprint helper).

Other doctor_hc_meta_full tests live in sibling files.

Schema scaffolding shared via _doctor_hc_meta_full_test_helpers (private module).
Uses in-memory SQLite and mock subprocess for deterministic testing.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_events_destructive_maintenance_audit,
    hc_events_historical_coverage_collapse,
    hc_events_synthetic_contamination,
)

from yoke_core.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_ISO,
    _args,
    _ensure_migration_audit_table,
    _completed,
    _iso_days_ago,
    _iso_minutes_ago,
    _make_conn,
    _p,
    _result,
    _results,
    _run_hc,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


class TestEventsSyntheticContamination:
    """HC-events-synthetic-contamination."""

    def test_pass_clean_events_table(self):
        conn = _make_conn()
        p = _p(conn)
        # One normal event, one correctly flagged backfill row.
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, anomaly_flags, "
            "created_at) VALUES "
            "(1, 'e-1', 'ItemStatusChanged', 'item_status_change', "
            f" 'lifecycle', 'system', 'session-a', 'cli', NULL, {p})",
            (_NOW_ISO,),
        )
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, anomaly_flags, "
            "created_at) VALUES "
            "(2, 'e-2', 'ItemStatusChanged', 'item_status_change', "
            " 'lifecycle', 'system', 'lifetime-activity-backfill', "
            f" 'backfill-lifetime-activity', 'historical_backfill', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_synthetic_contamination, conn)
        assert _result(rec).result == "PASS"

    def test_warn_legacy_activity_backfill(self):
        conn = _make_conn()
        p = _p(conn)
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, created_at) "
            "VALUES (1, 'legacy-1', 'ActivityBackfilled', "
            f"'activity_backfill', 'lifecycle', 'system', 'old', 'old', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_synthetic_contamination, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "legacy activity_backfill" in res.detail

    def test_warn_unflagged_backfill_marker(self):
        conn = _make_conn()
        p = _p(conn)
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, anomaly_flags, "
            "created_at) VALUES "
            "(1, 'e-1', 'ItemStatusChanged', 'item_status_change', "
            " 'lifecycle', 'system', 'lifetime-activity-backfill', "
            f" 'backfill-lifetime-activity', NULL, {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_synthetic_contamination, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "historical_backfill" in res.detail

    def test_warn_test_harness_marker(self):
        conn = _make_conn()
        p = _p(conn)
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, created_at) "
            "VALUES (1, 'e-1', 'T', 'T', 'T', 'system', 'pytest-xyz', "
            f"'cli', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_synthetic_contamination, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "test-harness" in res.detail


class TestEventsHistoricalCoverageCollapse:
    """HC-events-historical-coverage-collapse."""

    def test_pass_insufficient_history(self):
        conn = _make_conn()
        p = _p(conn)
        # Only 1 week with any rows → less than 4 buckets → PASS with note.
        conn.execute(
            "INSERT INTO events (id, event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, created_at) "
            "VALUES (1, 'e-1', 'ItemStatusChanged', 'isc', 'lifecycle', "
            f"'system', 's', 'cli', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_historical_coverage_collapse, conn)
        assert _result(rec).result == "PASS"

    def test_pass_steady_coverage(self):
        conn = _make_conn()
        p = _p(conn)
        # Insert 5 per week across 12 weeks — uniform, no collapse.
        for week_offset in range(12):
            for row_in_week in range(5):
                day_offset = week_offset * 7 + row_in_week
                conn.execute(
                    "INSERT INTO events (event_id, event_name, event_type, "
                    "event_kind, source_type, session_id, service, "
                    f"created_at) VALUES ({p}, 'ItemStatusChanged', 'isc', "
                    f"'lifecycle', 'system', 's', 'cli', {p})",
                    (f"e-{week_offset}-{row_in_week}", _iso_days_ago(day_offset)),
                )
        rec = _run_hc(hc_events_historical_coverage_collapse, conn)
        assert _result(rec).result == "PASS"

    def test_warn_collapsed_window(self):
        conn = _make_conn()
        p = _p(conn)
        # 11 weeks with 20 rows each, plus one week with 1 row → the sparse
        # week trips the 80% collapse threshold against the median (20 → 1).
        for week_offset in range(11):
            for row_in_week in range(20):
                day_offset = week_offset * 7 + row_in_week // 3
                conn.execute(
                    "INSERT INTO events (event_id, event_name, event_type, "
                    "event_kind, source_type, session_id, service, "
                    f"created_at) VALUES ({p}, 'ItemStatusChanged', 'isc', "
                    f"'lifecycle', 'system', 's', 'cli', {p})",
                    (f"e-{week_offset}-{row_in_week}", _iso_days_ago(day_offset)),
                )
        # Sparse 12th week
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, created_at) "
            "VALUES ('sparse-1', 'ItemStatusChanged', 'isc', 'lifecycle', "
            f"'system', 's', 'cli', {p})",
            (_iso_days_ago(82),),
        )
        rec = _run_hc(hc_events_historical_coverage_collapse, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "to_char((created_at)::timestamptz, 'YYYY-MM-DD')" in res.detail
        assert "strftime" not in res.detail

    def test_backfill_rows_ignored(self):
        conn = _make_conn()
        p = _p(conn)
        # Backfill rows (historical_backfill flag) must be excluded from
        # the coverage computation. With only excluded rows present, the
        # HC falls back to the "insufficient history" PASS branch rather
        # than treating backfill volume as real telemetry.
        for week_offset in range(12):
            conn.execute(
                "INSERT INTO events (event_id, event_name, event_type, "
                "event_kind, source_type, session_id, service, "
                f"anomaly_flags, created_at) VALUES ({p}, 'ItemStatusChanged', "
                "'isc', 'lifecycle', 'system', "
                "'lifetime-activity-backfill', 'backfill-lifetime-activity',"
                f" 'historical_backfill', {p})",
                (f"bf-{week_offset}", _iso_days_ago(week_offset * 7)),
            )
        rec = _run_hc(hc_events_historical_coverage_collapse, conn)
        res = _result(rec)
        assert res.result == "PASS"
        assert "insufficient history" in res.detail.lower()


class TestEventsDestructiveMaintenanceAudit:
    """HC-events-destructive-maintenance-audit."""

    def test_pass_no_audit_table(self):
        conn = _make_conn()
        # No migration_audit table → PASS with skip note.
        rec = _run_hc(hc_events_destructive_maintenance_audit, conn)
        assert _result(rec).result == "PASS"

    def test_pass_alarm_with_matching_audit(self):
        conn = _make_conn()
        _ensure_migration_audit_table(conn)
        p = _p(conn)
        # Alarm + matching audit row within ±1h.
        envelope = json.dumps(
            {"context": {"detail": {"command": "events prune"}}}
        )
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, envelope, "
            "created_at) VALUES ('alarm-1', 'DataLossDetected', 'db_alarm', "
            f"'system', 'hook', 's', 'cli', {p}, {p})",
            (envelope, _NOW_ISO),
        )
        conn.execute(
            "INSERT INTO migration_audit (migration_name, description, "
            "tables_declared, expected_deltas, pre_row_counts, "
            "backup_path, state, exception_reason, started_at) VALUES "
            "('events-prune', 'retention prune', '[\"events\"]', "
            "'{\"events\": -100}', '{\"events\": 500}', '', 'completed', "
            f"'Retention-only exception, bounded by severity/age.', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_destructive_maintenance_audit, conn)
        assert _result(rec).result == "PASS"

    def test_warn_alarm_without_audit(self):
        conn = _make_conn()
        _ensure_migration_audit_table(conn)
        p = _p(conn)
        envelope = json.dumps(
            {"context": {"detail": {"command": "sqlite3 drop events"}}}
        )
        conn.execute(
            "INSERT INTO events (event_id, event_name, event_type, "
            "event_kind, source_type, session_id, service, envelope, "
            "created_at) VALUES ('alarm-1', 'DataLossDetected', 'db_alarm', "
            f"'system', 'hook', 's', 'cli', {p}, {p})",
            (envelope, _NOW_ISO),
        )
        rec = _run_hc(hc_events_destructive_maintenance_audit, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "DataLossDetected" in res.detail
        assert "no migration_audit row" in res.detail

    def test_warn_exception_fingerprint_thin_rationale(self):
        conn = _make_conn()
        _ensure_migration_audit_table(conn)
        p = _p(conn)
        # Exception fingerprint with empty rationale → WARN.
        conn.execute(
            "INSERT INTO migration_audit (migration_name, description, "
            "tables_declared, expected_deltas, pre_row_counts, "
            "backup_path, state, exception_reason, started_at) VALUES "
            "('events-prune', 'retention', '[\"events\"]', "
            "'{\"events\": -10}', '{\"events\": 100}', '', 'completed', "
            f"'', {p})",
            (_NOW_ISO,),
        )
        rec = _run_hc(hc_events_destructive_maintenance_audit, conn)
        res = _result(rec)
        assert res.result == "WARN"
        assert "rationale note" in res.detail


class TestAuditFingerprintHelper:
    """record_audit_fingerprint lightweight emission helper."""

    def test_fingerprint_is_persisted(self, tmp_path):
        from runtime.api.fixtures.file_test_db import (
            connect_test_db,
            init_test_db,
        )

        def _apply_schema() -> None:
            from yoke_core.domain import db_backend

            c = db_backend.connect()
            try:
                apply_fixture_ddl(
                    c,
                    "CREATE TABLE events (id INTEGER PRIMARY KEY);",
                )
                _ensure_migration_audit_table(c)
                c.commit()
            finally:
                c.close()

        with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
            setup = connect_test_db(db_path)
            try:
                # Seed a few rows so pre/post counts are meaningful.
                for i in range(5):
                    setup.execute("INSERT INTO events DEFAULT VALUES")
                setup.commit()
            finally:
                setup.close()

            from yoke_core.domain.migration_harness import (
                record_audit_fingerprint,
            )

            record_audit_fingerprint(
                db_path=db_path,
                name="events-prune",
                description="retention-only prune",
                tables=["events"],
                pre_counts={"events": 5},
                post_counts={"events": 5},
                exception_reason="bounded retention safety exception",
            )

            check = connect_test_db(db_path)
            try:
                row = check.execute(
                    "SELECT migration_name, state, exception_reason, "
                    "pre_row_counts, post_row_counts FROM migration_audit "
                    "WHERE migration_name = 'events-prune' ORDER BY id DESC "
                    "LIMIT 1"
                ).fetchone()
            finally:
                check.close()

        assert row is not None
        assert row[0] == "events-prune"
        assert row[1] == "completed"
        assert "bounded retention" in row[2]
        assert '"events": 5' in row[3]
        assert '"events": 5' in row[4]

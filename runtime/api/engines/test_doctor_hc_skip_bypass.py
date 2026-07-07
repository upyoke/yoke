"""Tests for the manual skip-polish bypass Doctor HC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.engines.doctor_hc_skip_bypass import hc_skip_polish_manual_hop
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _ts(offset_seconds: int = 0) -> str:
    when = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_schema() -> None:
    conn = connect_test_db("")
    try:
        apply_fixture_ddl(conn, """
            CREATE TABLE item_status_transitions (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL,
                task_num INTEGER,
                from_status TEXT,
                to_status TEXT NOT NULL,
                source TEXT,
                session_id TEXT,
                actor_id INTEGER,
                project_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
    finally:
        conn.close()


def _record(
    conn,
    item_id: int,
    from_status: str,
    to_status: str,
    created_at: str,
    *,
    source: str = "backlog-registry",
) -> None:
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id, from_status, to_status, source, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (item_id, from_status, to_status, source, created_at),
    )


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_skip_polish_manual_hop(conn, DoctorArgs(), rec)
    return rec


def test_manual_skip_hop_warns_on_sub_minute_sequence(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            _record(
                conn,
                42,
                "reviewed-implementation",
                "polishing-implementation",
                _ts(-30),
            )
            _record(conn, 42, "polishing-implementation", "implemented", _ts(-5))
            conn.commit()

            rec = _run(conn)
        finally:
            conn.close()

    assert rec.results[0].result == "WARN"
    assert "YOK-42" in rec.results[0].detail
    assert "25s" in rec.results[0].detail


def test_manual_skip_hop_passes_when_gap_is_longer_than_one_minute(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            _record(
                conn,
                43,
                "reviewed-implementation",
                "polishing-implementation",
                _ts(-300),
            )
            _record(conn, 43, "polishing-implementation", "implemented", _ts(-120))
            conn.commit()

            rec = _run(conn)
        finally:
            conn.close()

    assert rec.results[0].result == "PASS"


def test_manual_skip_hop_ignores_sanctioned_skip_polish_source(tmp_path):
    """The --skip-polish surface stamps its own source; only raw
    backlog-registry pairs are the anti-pattern."""
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            _record(
                conn,
                44,
                "reviewed-implementation",
                "polishing-implementation",
                _ts(-30),
                source="skip-polish",
            )
            _record(
                conn, 44, "polishing-implementation", "implemented", _ts(-5),
                source="skip-polish",
            )
            conn.commit()

            rec = _run(conn)
        finally:
            conn.close()

    assert rec.results[0].result == "PASS"

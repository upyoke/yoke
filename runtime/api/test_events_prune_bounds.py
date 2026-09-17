"""Bounded event-retention tests for ``cmd_prune``."""

from __future__ import annotations

import threading
import time

from yoke_core.domain import db_backend, events_crud as ec
from yoke_core.domain.events_prune_batches import prune_matching_events
from runtime.api.events_crud_test_fixtures import _iso_offset_days
from runtime.api.fixtures.file_test_db import connect_test_db

pytest_plugins = ("runtime.api.events_crud_test_fixtures",)


def _insert(
    db_path: str,
    event_id: str,
    *,
    severity: str,
    days: int,
    event_name: str = "N",
) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO events (event_id, source_type, session_id, severity, "
            "event_kind, event_type, event_name, created_at) "
            "VALUES (%s, 'agent', 's1', %s, 'k', 't', %s, %s)",
            (event_id, severity, event_name, _iso_offset_days(days)),
        )
        conn.commit()
    finally:
        conn.close()


def _count(db_path: str, event_id: str | None = None) -> int:
    conn = connect_test_db(db_path)
    try:
        if event_id is None:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_id = %s",
                (event_id,),
            ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def test_info_cutoff_and_status_retained(db_path: str) -> None:
    _insert(db_path, "old-info", severity="INFO", days=-31)
    _insert(db_path, "new-info", severity="INFO", days=-29)
    _insert(db_path, "old-status", severity="STATUS", days=-365)
    result = ec.cmd_prune(db_path)
    assert "INFO=1" in result
    assert _count(db_path, "old-info") == 0
    assert _count(db_path, "new-info") == 1
    assert _count(db_path, "old-status") == 1


def test_dry_run_partial_label(db_path: str) -> None:
    for index in range(3):
        _insert(db_path, f"old-debug-{index}", severity="DEBUG", days=-8)
    result = ec.cmd_prune(db_path, dry_run=True, batch_size=2)
    assert "DEBUG=>=2 (partial)" in result
    assert _count(db_path) == 3


def test_batch_resume_continues_leftovers(db_path: str) -> None:
    for index in range(5):
        _insert(db_path, f"old-info-{index}", severity="INFO", days=-40)
    first = ec.cmd_prune(db_path, batch_size=2, max_batches=1)
    assert "INFO=2" in first
    assert "stopped: batch/time budget" in first
    assert _count(db_path) == 3
    second = ec.cmd_prune(db_path, batch_size=2, max_batches=1)
    assert "INFO=2" in second
    third = ec.cmd_prune(db_path, batch_size=2, max_batches=1)
    assert "INFO=1" in third
    assert "stopped: batch/time budget" not in third
    assert _count(db_path) == 0


def test_skips_obsolete_by_default(db_path: str) -> None:
    _insert(
        db_path,
        "obsolete-now",
        severity="STATUS",
        days=0,
        event_name="Gen3I6CleanRoomSmoke",
    )
    result = ec.cmd_prune(db_path)
    assert "obsolete=0" in result
    assert _count(db_path, "obsolete-now") == 1


def test_referenced_expired_info_is_kept(db_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute("CREATE TABLE path_moves (recorded_event_id TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()
    _insert(db_path, "pinned-info", severity="INFO", days=-40)
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO path_moves (recorded_event_id) VALUES ('pinned-info')"
        )
        conn.commit()
    finally:
        conn.close()
    result = ec.cmd_prune(db_path)
    assert "INFO=0" in result
    assert _count(db_path, "pinned-info") == 1


def test_concurrent_insert_keeps_in_window_rows(db_path: str) -> None:
    for index in range(20):
        _insert(db_path, f"old-{index}", severity="INFO", days=-40)
    barrier = threading.Barrier(2)

    def _insert_fresh() -> None:
        barrier.wait()
        _insert(db_path, "fresh-info", severity="INFO", days=-1)

    worker = threading.Thread(target=_insert_fresh)
    worker.start()
    barrier.wait()
    ec.cmd_prune(db_path, batch_size=5)
    worker.join()
    assert _count(db_path, "fresh-info") == 1
    leftover_old = sum(_count(db_path, f"old-{index}") for index in range(20))
    assert leftover_old == 0


def test_time_budget_stops_then_rerun_finishes(db_path: str) -> None:
    for index in range(4):
        _insert(db_path, f"old-info-{index}", severity="INFO", days=-40)
    first = ec.cmd_prune(db_path, batch_size=1, max_batches=1)
    assert "stopped: batch/time budget" in first
    remaining = _count(db_path)
    assert remaining == 3
    ec.cmd_prune(db_path)
    assert _count(db_path) == 0


def test_slow_statement_returns_partial_without_deleting(db_path: str) -> None:
    """One timed-out statement stops the pass; committed work (none) stands."""
    _insert(db_path, "old-info", severity="INFO", days=-40)
    conn = connect_test_db(db_path)
    try:
        if not db_backend.connection_is_postgres(conn):
            return
        deleted, remaining = prune_matching_events(
            conn,
            "(SELECT pg_sleep(5)) IS NOT NULL",
            batch_size=1,
            deadline=time.monotonic() + 0.25,
        )
        assert deleted == 0
        assert remaining is True
    finally:
        conn.close()
    assert _count(db_path, "old-info") == 1


def test_restores_preexisting_nonzero_timeout(db_path: str) -> None:
    """Incoming diagnostic timeout must survive probes and cancellation."""
    from yoke_core.domain.events_prune_batches import (
        StatementBudgetExceeded,
        current_statement_timeout,
        execute_with_deadline,
    )
    from yoke_core.domain.events_prune import _purged_event_where, _severity_where
    from yoke_core.domain.events_prune_report import dry_run_report

    conn = connect_test_db(db_path)
    try:
        if not db_backend.connection_is_postgres(conn):
            return
        conn.execute("SELECT set_config('statement_timeout', %s, true)", ("30s",))
        incoming = current_statement_timeout(conn)
        assert incoming not in {"0", "0ms", "0s"}
        dry_run_report(
            conn,
            10,
            False,
            False,
            deadline=time.monotonic() + 30,
            severity_where=_severity_where,
            purged_event_where=_purged_event_where,
        )
        assert current_statement_timeout(conn) == incoming
        try:
            execute_with_deadline(
                conn,
                time.monotonic() + 0.25,
                "SELECT pg_sleep(5)",
                restore_timeout=incoming,
            )
        except StatementBudgetExceeded:
            pass
        assert current_statement_timeout(conn) == incoming
        conn.execute("SELECT pg_sleep(0.2)")
    finally:
        conn.close()


def test_prune_cli_kwargs_parses_bounds() -> None:
    kwargs = ec.prune_cli_kwargs(
        [
            "--dry-run",
            "--purge-obsolete",
            "--batch-size",
            "10",
            "--max-seconds",
            "5",
            "--max-batches",
            "3",
        ]
    )
    assert kwargs == {
        "dry_run": True,
        "purge_obsolete": True,
        "batch_size": 10,
        "max_seconds": 5.0,
        "max_batches": 3,
    }

"""Unit tests for ``HC-executor-canonicalization``.

Each test seeds a minimal ``harness_sessions`` table in a disposable
Postgres test database, runs the HC, and asserts the recorded verdict +
offender detail. The schema-skip test exercises the minimal-schema
fixture install (no ``harness_sessions`` table at all).
"""

from __future__ import annotations

from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.executor_canonical_labels import (
    CANONICAL_HARNESS_IDS,
    KNOWN_SURFACE_LABELS,
)
from yoke_core.engines.doctor_hc_executor_canonicalization import (
    HC_LABEL,
    HC_SLUG,
    hc_executor_canonicalization,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HARNESS_SESSIONS_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT 'claude-opus-4-7',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT DEFAULT '[]',
    workspace TEXT NOT NULL DEFAULT '/tmp',
    mode TEXT DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    executor_display_name TEXT
);
"""


def _empty_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )


@pytest.fixture
def db_conn():
    c = _empty_conn()
    apply_fixture_ddl(c, _HARNESS_SESSIONS_DDL)
    yield c
    c.close()


def _seed_session(
    conn,
    *,
    session_id: str,
    executor: str,
    executor_display_name: Optional[str] = None,
    ended_at: Optional[str] = None,
    offered_at: str = "2026-05-20T00:00:00+00:00",
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, executor_display_name, offered_at, "
        "last_heartbeat, ended_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            executor,
            executor_display_name,
            offered_at,
            offered_at,
            ended_at,
        ),
    )


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_executor_canonicalization(conn, DoctorArgs(), rec)
    return rec


def _only_result(rec: RecordCollector):
    assert len(rec.results) == 1
    return rec.results[0]


def test_pass_when_only_canonical_rows(db_conn):
    """AC-3: canonical executor rows do not trip the HC."""
    _seed_session(
        db_conn,
        session_id="s-1",
        executor="claude-code",
        executor_display_name="claude-desktop",
    )
    _seed_session(
        db_conn,
        session_id="s-2",
        executor="codex",
        executor_display_name=None,
    )
    _seed_session(
        db_conn,
        session_id="s-3",
        executor="claude-code",
        executor_display_name=None,
    )

    result = _only_result(_run_hc(db_conn))

    assert result.check_id == HC_SLUG
    assert result.check_name == HC_LABEL
    assert result.result == "PASS"
    for canonical in CANONICAL_HARNESS_IDS:
        assert canonical in result.detail


def test_warn_when_leaked_with_null_display_name(db_conn):
    """AC-2: ``executor='claude-desktop'`` with NULL display_name trips."""
    _seed_session(
        db_conn,
        session_id="s-leak-null",
        executor="claude-desktop",
        executor_display_name=None,
    )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "WARN"
    assert "s-leak-null" in result.detail
    assert "claude-desktop" in result.detail
    assert "<NULL>" in result.detail
    assert "/yoke idea" in result.detail


def test_warn_when_leaked_with_populated_display_name(db_conn):
    """AC-9: populated display_name does not exempt a leaked executor."""
    _seed_session(
        db_conn,
        session_id="s-leak-populated",
        executor="claude-desktop",
        executor_display_name="claude-desktop",
    )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "WARN"
    assert "s-leak-populated" in result.detail
    assert "claude-desktop" in result.detail
    assert "<NULL>" not in result.detail


def test_warn_catches_future_surface_label_via_pattern(db_conn):
    """AC-8: pattern detection trips on a Yoke-family surface
    label not present in :data:`KNOWN_SURFACE_LABELS`."""
    novel_surface = "codex-jetbrains"
    assert novel_surface not in KNOWN_SURFACE_LABELS

    _seed_session(
        db_conn,
        session_id="s-future",
        executor=novel_surface,
    )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "WARN"
    assert novel_surface in result.detail
    assert "s-future" in result.detail


def test_ended_sessions_are_excluded(db_conn):
    """Leaked rows already terminated are not active drift."""
    _seed_session(
        db_conn,
        session_id="s-ended",
        executor="claude-desktop",
        ended_at="2026-05-19T00:00:00+00:00",
    )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "PASS"


def test_unrelated_custom_executor_does_not_trip(db_conn):
    """Custom ``YOKE_EXECUTOR`` values that are not Yoke-family
    do not pattern-match and are not flagged."""
    _seed_session(
        db_conn,
        session_id="s-custom",
        executor="my-fork-runner",
    )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "PASS"


def test_skip_on_minimal_schema():
    """The HC reports SKIP when ``harness_sessions`` is absent."""
    c = _empty_conn()
    try:
        result = _only_result(_run_hc(c))
    finally:
        c.close()

    assert result.result == "SKIP"
    assert "harness_sessions" in result.detail


def test_offender_list_truncates_with_overflow_marker(db_conn):
    """More than ``_MAX_OFFENDERS_REPORTED`` leaked rows show a
    ``... +N more`` overflow line."""
    from yoke_core.engines.doctor_hc_executor_canonicalization import (
        _MAX_OFFENDERS_REPORTED,
    )

    overflow = 3
    total = _MAX_OFFENDERS_REPORTED + overflow
    for i in range(total):
        _seed_session(
            db_conn,
            session_id=f"s-leak-{i:02d}",
            executor="claude-desktop",
            offered_at=f"2026-05-20T00:00:{i:02d}+00:00",
        )

    result = _only_result(_run_hc(db_conn))

    assert result.result == "WARN"
    assert f"{total} active session(s)" in result.detail
    assert f"+{overflow} more" in result.detail

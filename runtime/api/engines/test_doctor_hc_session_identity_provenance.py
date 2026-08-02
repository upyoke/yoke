"""Unit tests for ``HC-session-identity-provenance``.

Each test seeds a minimal ``harness_sessions`` (and, where the actor scan
is exercised, ``events``) table in a disposable Postgres test database,
runs the HC, and asserts the recorded verdict plus offender detail.
"""

from __future__ import annotations

from typing import Optional

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_project_checks.check_session_identity_provenance import (
    HC_SLUG,
    PROJECT_HEALTH_CHECKS,
    hc_session_identity_provenance,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HARNESS_SESSIONS_DDL = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT 'claude-opus-4-7',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    workspace TEXT NOT NULL DEFAULT '/tmp',
    mode TEXT DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    executor_display_name TEXT
);
"""

_EVENTS_DDL = """
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    event_id TEXT,
    session_id TEXT,
    event_name TEXT,
    created_at TEXT
);
"""

_REAL_UUID = "019fb914-2b50-7133-8065-e174775dc981"
_OTHER_UUID = "f6300c3b-4a37-4b08-aa56-65d11c5a22e2"
_WHEN = "2026-05-20T00:00:00+00:00"


def _empty_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )


@pytest.fixture
def sessions_only():
    c = _empty_conn()
    apply_fixture_ddl(c, _HARNESS_SESSIONS_DDL)
    yield c
    c.close()


@pytest.fixture
def sessions_and_events():
    c = _empty_conn()
    apply_fixture_ddl(c, _HARNESS_SESSIONS_DDL)
    apply_fixture_ddl(c, _EVENTS_DDL)
    yield c
    c.close()


def _seed_session(
    conn,
    *,
    session_id: str,
    executor: str = "codex",
    executor_display_name: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, executor_display_name, offered_at, "
        "last_heartbeat, ended_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (session_id, executor, executor_display_name, _WHEN, _WHEN, ended_at),
    )


def _seed_event(conn, *, session_id: str) -> None:
    conn.execute(
        "INSERT INTO events (session_id, event_name, created_at) "
        "VALUES (%s, %s, %s)",
        (session_id, "YokeFunctionCalled", _WHEN),
    )


def _run(conn):
    rec = RecordCollector()
    hc_session_identity_provenance(conn, DoctorArgs(), rec)
    assert len(rec.results) == 1
    return rec.results[0]


def test_module_declares_the_check_for_discovery():
    """A check that runs correctly but declares nothing never runs at all."""
    assert [c.slug for c in PROJECT_HEALTH_CHECKS] == [
        "session-identity-provenance"
    ]
    assert PROJECT_HEALTH_CHECKS[0].fn is hc_session_identity_provenance


def test_skips_when_sessions_table_absent():
    conn = _empty_conn()
    try:
        assert _run(conn).result == "SKIP"
    finally:
        conn.close()


def test_passes_on_known_labels_and_null(sessions_only):
    _seed_session(
        sessions_only, session_id="s-1", executor="codex",
        executor_display_name="codex-desktop",
    )
    _seed_session(
        sessions_only, session_id="s-2", executor="claude-code",
        executor_display_name=None,
    )
    _seed_session(
        sessions_only, session_id="s-3", executor="claude-code",
        executor_display_name="claude-cli",
    )
    result = _run(sessions_only)
    assert result.check_id == HC_SLUG
    assert result.result == "PASS"


def test_warns_on_unrecognized_display_name(sessions_only):
    _seed_session(
        sessions_only, session_id="s-bad", executor="codex",
        executor_display_name="codex-dash",
    )
    result = _run(sessions_only)
    assert result.result == "WARN"
    assert "codex-dash" in result.detail
    assert "s-bad" in result.detail


def test_ended_sessions_are_left_alone(sessions_only):
    # Settled history stays quiet without an exemption list: the check is
    # about writers still producing bad identity, not rows already written.
    _seed_session(
        sessions_only, session_id="s-old", executor="codex",
        executor_display_name="codex-goal", ended_at=_WHEN,
    )
    assert _run(sessions_only).result == "PASS"


def test_warns_on_uuid_actor_with_no_session_row(sessions_and_events):
    _seed_session(
        sessions_and_events, session_id=_REAL_UUID,
        executor_display_name="codex-desktop",
    )
    _seed_event(sessions_and_events, session_id=_REAL_UUID)
    _seed_event(sessions_and_events, session_id=_OTHER_UUID)
    result = _run(sessions_and_events)
    assert result.result == "WARN"
    assert _OTHER_UUID in result.detail
    assert _REAL_UUID not in result.detail


def test_service_pseudo_sessions_are_not_flagged(sessions_and_events):
    # Sweeps, hosted UI, and audits are deliberately slug-named actors with
    # no harness conversation behind them.
    for actor in ("__sweep__", "doorman-ui", "atlas-integrity-audit", "hc"):
        _seed_event(sessions_and_events, session_id=actor)
    assert _run(sessions_and_events).result == "PASS"


def test_passes_when_every_actor_is_registered(sessions_and_events):
    _seed_session(
        sessions_and_events, session_id=_REAL_UUID,
        executor_display_name="codex-desktop",
    )
    _seed_event(sessions_and_events, session_id=_REAL_UUID)
    assert _run(sessions_and_events).result == "PASS"

"""Tests for ``HC-event-outcome-drift`` (YOK-1761 task 4)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from unittest import mock

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_event_outcome_drift import (
    HC_ID,
    hc_event_outcome_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_EVENTS_DDL = """
CREATE TABLE events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL,
    event_outcome TEXT,
    exit_code INTEGER,
    envelope TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE migration_audit (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    migration_name TEXT NOT NULL,
    model_name TEXT,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL
);
"""


@pytest.fixture
def db_conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, _EVENTS_DDL)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


@pytest.fixture
def isolated_config(tmp_path: Path):
    """Point runtime_settings at an empty per-test config file so the
    cutover marker is controllable per test."""
    config_path = tmp_path / ".yoke" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"settings": {}}\n')
    with mock.patch.dict(
        os.environ,
        {"YOKE_MACHINE_CONFIG_FILE": str(config_path)},
    ):
        yield config_path


def _write_setting(config_path: Path, key: str, value: object) -> None:
    payload = json.loads(config_path.read_text())
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    settings[key] = value
    payload["settings"] = settings
    config_path.write_text(json.dumps(payload, sort_keys=True) + "\n")


def _set_cutover_marker(config_path: Path, when: str) -> None:
    _write_setting(config_path, "event_outcome_drift_cutover_at", when)


def _set_tolerance(config_path: Path, tolerance: int) -> None:
    _write_setting(config_path, "event_outcome_drift_pre_cutover_warn_max", tolerance)


def _seed_event(
    conn,
    *,
    created_at: str,
    envelope: Optional[Dict[str, Any]] = None,
    exit_code: Optional[int] = 0,
    event_name: str = "HarnessToolCallCompleted",
    event_outcome: str = "completed",
) -> str:
    event_id = str(uuid.uuid4())
    envelope_text = json.dumps(envelope) if envelope is not None else None
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_outcome, "
        "exit_code, envelope, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (event_id, event_name, event_outcome, exit_code, envelope_text, created_at),
    )
    conn.commit()
    return event_id


def _envelope_with_exit(exit_code: int) -> Dict[str, Any]:
    return {
        "context": {
            "detail": {
                "tool_name": "Bash",
                "tool_response_preview": f"some output\nExit code {exit_code}\n",
            }
        }
    }


def _envelope_with_error(error: str) -> Dict[str, Any]:
    return {
        "context": {
            "detail": {
                "tool_name": "Bash",
                "error": error,
            }
        }
    }


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_event_outcome_drift(conn, DoctorArgs(), rec)
    return rec


def test_skip_when_no_cutover_marker_and_no_audit_row(db_conn, isolated_config) -> None:
    """Without a marker AND without a backfill_event_outcomes audit row,
    the HC PASSes with a cutover-not-yet-applied advisory so the check
    is silent on pre-apply environments."""
    _seed_event(db_conn, created_at="2026-01-01T00:00:00Z")
    rec = _run(db_conn)
    assert rec.results[-1].result == "PASS"
    assert "cutover-not-yet-applied" in rec.results[-1].detail


def test_warns_when_completed_audit_row_exists_without_marker(
    db_conn, isolated_config
) -> None:
    """The audit row proves the backfill ran, not that live emitters are
    deployed. Without an explicit marker, the HC warns instead of
    inventing a post-cutover boundary."""
    db_conn.execute(
        "INSERT INTO migration_audit (migration_name, model_name, state, started_at) "
        "VALUES (%s, %s, %s, %s)",
        ("backfill_event_outcomes", "primary", "test_apply_failed",
         "2026-02-01T00:00:00Z"),
    )
    db_conn.execute(
        "INSERT INTO migration_audit (migration_name, model_name, state, started_at) "
        "VALUES (%s, %s, %s, %s)",
        ("backfill_event_outcomes", "primary", "completed",
         "2026-03-01T00:00:00Z"),
    )
    db_conn.commit()
    # A drift-shaped row is not classified post-cutover until the explicit
    # marker exists.
    _seed_event(
        db_conn,
        created_at="2026-04-01T00:00:00Z",
        envelope={"_truncated": True, "context": {"detail": {"error": "boom"}}},
        exit_code=0,
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "WARN"
    assert "cutover-marker-missing" in rec.results[-1].detail


def test_pass_when_no_drift(db_conn, isolated_config) -> None:
    """Zero post-cutover drift AND zero pre-cutover residual is PASS."""
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    _seed_event(db_conn, created_at="2026-04-01T00:00:00Z", exit_code=0)
    rec = _run(db_conn)
    assert rec.results[-1].result == "PASS"
    assert "No post-cutover drift" in rec.results[-1].detail


def test_warn_with_pre_cutover_residual(db_conn, isolated_config) -> None:
    """Pre-cutover residual within tolerance is WARN, not FAIL."""
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    _seed_event(
        db_conn,
        created_at="2026-02-01T00:00:00Z",
        envelope=_envelope_with_exit(7),
        exit_code=0,
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "WARN"
    assert "1 legacy pre-cutover row" in rec.results[-1].detail


def test_fail_when_pre_cutover_residual_exceeds_tolerance(
    db_conn, isolated_config
) -> None:
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    _set_tolerance(isolated_config, 0)
    _seed_event(
        db_conn,
        created_at="2026-02-01T00:00:00Z",
        envelope=_envelope_with_error("boom"),
        exit_code=0,
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "FAIL"
    assert "exceeds tolerance" in rec.results[-1].detail


def test_fail_when_post_cutover_drift_present(db_conn, isolated_config) -> None:
    """A post-cutover row with the drift shape is a regression in the
    live emitters and must FAIL."""
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    _seed_event(
        db_conn,
        created_at="2026-04-01T00:00:00Z",
        envelope=_envelope_with_exit(7),
        exit_code=7,  # positive exit_code on a 'completed' row = drift
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "FAIL"
    assert "post-cutover row" in rec.results[-1].detail
    assert "regression in the live emitters" in rec.results[-1].detail


def test_fail_dominates_over_residual(db_conn, isolated_config) -> None:
    """If both post-cutover drift and pre-cutover residual exist, the
    FAIL on post-cutover regression takes precedence."""
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    # Pre-cutover residual.
    _seed_event(
        db_conn,
        created_at="2026-02-01T00:00:00Z",
        envelope=_envelope_with_exit(2),
        exit_code=0,
    )
    # Post-cutover drift.
    _seed_event(
        db_conn,
        created_at="2026-04-01T00:00:00Z",
        envelope=_envelope_with_error("boom"),
        exit_code=0,
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "FAIL"
    assert "post-cutover row" in rec.results[-1].detail


def test_ignores_non_target_event_names(db_conn, isolated_config) -> None:
    """Rows for unrelated event_names must NEVER raise the HC."""
    _set_cutover_marker(isolated_config, "2026-03-01T00:00:00Z")
    _seed_event(
        db_conn,
        created_at="2026-04-01T00:00:00Z",
        envelope=_envelope_with_exit(7),
        exit_code=7,
        event_name="SomeOtherEvent",
    )
    rec = _run(db_conn)
    assert rec.results[-1].result == "PASS"


def test_hc_id_matches_registered_string(db_conn, isolated_config) -> None:
    """Defense in depth — the HC id reported in the record must match
    the canonical id surfaced in the doctor registry."""
    _seed_event(db_conn, created_at="2026-04-01T00:00:00Z", exit_code=0)
    rec = _run(db_conn)
    assert rec.results[-1].check_id == f"HC-{HC_ID}"

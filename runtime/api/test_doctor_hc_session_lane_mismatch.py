"""HC-session-lane-mismatch coverage.

Exercises the detection of live sessions where the persisted
``offer_envelope.execution_lane`` disagrees with the authoritative
``harness_sessions.execution_lane`` row value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_session_lane_mismatch import (
    HC_LABEL,
    HC_SLUG,
    hc_session_lane_mismatch,
)


@dataclass
class _DoctorArgsStub:
    project: str = "yoke"
    fix: bool = False
    rebuild_board: bool = False


@dataclass
class _Record:
    slug: str
    label: str
    verdict: str
    detail: str


class _RecorderStub:
    def __init__(self) -> None:
        self.records: List[_Record] = []

    def record(self, slug: str, label: str, verdict: str, detail: str) -> None:
        self.records.append(_Record(slug, label, verdict, detail))


SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    execution_lane TEXT,
    offer_envelope TEXT,
    ended_at TEXT
);
"""


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, SCHEMA)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _insert(
    conn,
    *,
    session_id: str,
    row_lane: str | None,
    envelope_lane: str | None,
    ended_at: str | None = None,
) -> None:
    envelope_blob = None
    if envelope_lane is not None:
        envelope_blob = json.dumps({"execution_lane": envelope_lane})
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, execution_lane, offer_envelope, ended_at) "
        "VALUES (%s, %s, %s, %s)",
        (session_id, row_lane, envelope_blob, ended_at),
    )
    conn.commit()


def test_self_skips_on_minimal_schema():
    """Cold-start fixtures without the lane columns must PASS, not fail."""
    name = pg_testdb.create_test_database()
    cold = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(cold, "CREATE TABLE harness_sessions (session_id TEXT)")
    rec = _RecorderStub()
    hc_session_lane_mismatch(cold, _DoctorArgsStub(), rec)
    cold.close()
    pg_testdb.drop_test_database(name)
    assert rec.records[0].slug == HC_SLUG
    assert rec.records[0].verdict == "PASS"


def test_passes_when_envelope_matches_row(conn):
    _insert(conn, session_id="match", row_lane="DARIUS", envelope_lane="DARIUS")
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "PASS"


def test_passes_when_envelope_absent(conn):
    """Sessions registered but never offered carry no envelope lane."""
    _insert(conn, session_id="no-envelope", row_lane="DARIUS", envelope_lane=None)
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "PASS"


def test_warns_when_envelope_disagrees_with_row(conn):
    """The exact regression shape — primary envelope vs DARIUS row."""
    _insert(conn, session_id="bad", row_lane="DARIUS", envelope_lane="primary")
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "WARN"
    assert "bad" in rec.records[0].detail
    assert "DARIUS" in rec.records[0].detail
    assert "primary" in rec.records[0].detail


def test_does_not_flag_ended_sessions(conn):
    _insert(
        conn,
        session_id="ended",
        row_lane="DARIUS",
        envelope_lane="primary",
        ended_at="2026-04-01T00:00:00Z",
    )
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "PASS"


def test_flags_multiple_live_mismatches(conn):
    _insert(conn, session_id="bad-1", row_lane="DARIUS", envelope_lane="primary")
    _insert(conn, session_id="bad-2", row_lane="ALTMAN", envelope_lane="primary")
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "WARN"
    assert "bad-1" in rec.records[0].detail
    assert "bad-2" in rec.records[0].detail


def test_uses_canonical_slug_and_label(conn):
    _insert(conn, session_id="ok", row_lane="DARIUS", envelope_lane="DARIUS")
    rec = _RecorderStub()
    hc_session_lane_mismatch(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].slug == HC_SLUG
    assert rec.records[0].label == HC_LABEL

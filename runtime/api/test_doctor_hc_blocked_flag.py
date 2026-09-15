"""doctor health checks for the blocked flag model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_blocked_flag import (
    hc_blocked_flag_consistency,
    hc_blocked_status_drift,
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


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    # The findings name items by reference, so the fixture carries the
    # identity the renderer reads. Sequences deliberately differ from the
    # internal ids: a finding that named items.id would read as the wrong
    # item's reference.
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT,
            public_item_prefix TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            blocked INTEGER DEFAULT 0,
            blocked_reason TEXT
        );
        """,
    )
    c.execute(
        "INSERT INTO projects (id, slug, public_item_prefix) "
        "VALUES (1, 'yoke', 'YOK')"
    )
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def test_status_drift_passes_when_clean(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked) VALUES (1, 1, 701, 'idea', 0)")
    rec = _RecorderStub()
    hc_blocked_status_drift(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "PASS"


def test_status_drift_fails_when_legacy_status_remains(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked) VALUES (2, 1, 702, 'blocked', 0)")
    rec = _RecorderStub()
    hc_blocked_status_drift(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "FAIL"
    assert "YOK-702" in rec.records[0].detail


def test_status_drift_fails_when_both_status_and_flag_set(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked) VALUES (3, 1, 703, 'blocked', 1)")
    rec = _RecorderStub()
    hc_blocked_status_drift(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "FAIL"


def test_flag_consistency_passes_when_clean(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked, blocked_reason) VALUES (1, 1, 701, 'implementing', 1, 'paused')")
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked, blocked_reason) VALUES (2, 1, 702, 'idea', 0, NULL)")
    rec = _RecorderStub()
    hc_blocked_flag_consistency(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "PASS"


def test_flag_consistency_fails_when_blocked_without_reason(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked, blocked_reason) VALUES (3, 1, 703, 'idea', 1, NULL)")
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked, blocked_reason) VALUES (4, 1, 704, 'idea', 1, '')")
    rec = _RecorderStub()
    hc_blocked_flag_consistency(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "FAIL"
    assert "YOK-703" in rec.records[0].detail
    assert "YOK-704" in rec.records[0].detail


def test_flag_consistency_fails_when_unblocked_with_stale_reason(conn):
    conn.execute("INSERT INTO items (id, project_id, project_sequence, status, blocked, blocked_reason) VALUES (5, 1, 705, 'idea', 0, 'old reason')")
    rec = _RecorderStub()
    hc_blocked_flag_consistency(conn, _DoctorArgsStub(), rec)
    assert rec.records[0].verdict == "FAIL"
    assert "YOK-705" in rec.records[0].detail
    assert "old reason" in rec.records[0].detail

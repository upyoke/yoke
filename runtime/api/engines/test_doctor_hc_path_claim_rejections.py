"""Tests for HC-path-claim-register-rejected-with-deps."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.engines.doctor_hc_path_claim_rejections import (
    hc_path_claim_register_rejected_with_deps,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_ITEM_DEPS_DDL = """
CREATE TABLE item_dependencies (
    id INTEGER PRIMARY KEY,
    dependent_item TEXT NOT NULL,
    blocking_item TEXT NOT NULL,
    gate_point TEXT NOT NULL DEFAULT 'activation',
    satisfaction TEXT NOT NULL DEFAULT 'status:done',
    source TEXT NOT NULL,
    session_id INTEGER,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
)
"""

_PATH_CLAIMS_DDL = """
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    item_id INTEGER
)
"""


def _apply_schema() -> None:
    """``apply_schema`` strategy for the HC's minimal events + dep + claim DDL.

    Resolves its connection through the backend factory so the same DDL builds
    on SQLite and Postgres. The HC's ``_table_exists`` reads resolve through
    backend-native schema helpers.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.events_schema import _create_events_table

    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    conn = db_backend.connect()
    try:
        _create_events_table(conn)
        seed_project_identities(conn)
        apply_fixture_ddl(conn, _ITEM_DEPS_DDL)
        apply_fixture_ddl(conn, _PATH_CLAIMS_DDL)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _now_iso(offset_minutes: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    ).isoformat()


def _insert_blocked_event(
    conn,
    *,
    item_id: int,
    reason: str,
    blocking_claim_id: int | None = None,
    created_at: str | None = None,
) -> None:
    envelope = json.dumps({
        "context": {
            "reason": reason,
            "blocking_claim_id": blocking_claim_id,
        }
    })
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity, "
        "event_kind, event_type, event_name, project_id, item_id, "
        "envelope, created_at) "
        "VALUES (%s, 'system', '', 'WARN', 'lifecycle', 'path_claim', "
        "'PathClaimRegistrationBlocked', 1, %s, %s, %s)",
        (uuid.uuid4().hex, item_id, envelope, created_at or _now_iso()),
    )
    conn.commit()


def _add_dep_edge(
    conn, *, dependent: int, blocking: int,
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "source, created_at) VALUES (%s, %s, 'test', %s)",
        (f"YOK-{dependent}", f"YOK-{blocking}", _now_iso()),
    )
    conn.commit()


def _seed_path_claim(conn, *, claim_id: int, item_id: int) -> None:
    conn.execute(
        "INSERT INTO path_claims (id, item_id) VALUES (%s, %s)",
        (claim_id, item_id),
    )
    conn.commit()


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_path_claim_register_rejected_with_deps(conn, DoctorArgs(), rec)
    return rec


def test_pass_when_no_events(conn):
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_pass_when_overlap_event_has_no_dep_edges(conn):
    _insert_blocked_event(
        conn,
        item_id=8001,
        reason="path coverage overlaps an active claim on 'main'; "
               "declare an upstream dependency or wait",
    )
    # No item_dependencies edge for 8001 → benign rejection.
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_warn_when_overlap_event_has_dep_edges(conn):
    candidate = 8101
    upstream = 8102
    blocking_claim = 9102
    _seed_path_claim(conn, claim_id=blocking_claim, item_id=upstream)
    _insert_blocked_event(
        conn,
        item_id=candidate,
        reason="path coverage overlaps an active claim on 'main'; "
               "declare an upstream dependency or wait",
        blocking_claim_id=blocking_claim,
    )
    _add_dep_edge(conn, dependent=candidate, blocking=upstream)
    rec = _run_hc(conn)
    result = rec.results[0]
    assert result.result == "WARN"
    assert f"YOK-{candidate}" in result.detail
    assert "candidate_item_id" in result.detail


def test_pass_when_overlap_event_has_dep_edge_but_no_blocking_claim_id(conn):
    candidate = 8151
    upstream = 8152
    _insert_blocked_event(
        conn,
        item_id=candidate,
        reason="path coverage overlaps an active claim on 'main'; "
               "declare an upstream dependency or wait",
    )
    _add_dep_edge(conn, dependent=candidate, blocking=upstream)
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_pass_when_blocking_claim_owner_has_no_dep_edge(conn):
    candidate = 8161
    upstream = 8162
    blocking_claim = 9162
    _seed_path_claim(conn, claim_id=blocking_claim, item_id=upstream)
    _insert_blocked_event(
        conn,
        item_id=candidate,
        reason="path coverage overlaps an active claim on 'main'; "
               "declare an upstream dependency or wait",
        blocking_claim_id=blocking_claim,
    )
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_pass_when_event_outside_24h_window(conn):
    candidate = 8201
    upstream = 8202
    blocking_claim = 9202
    _seed_path_claim(conn, claim_id=blocking_claim, item_id=upstream)
    _insert_blocked_event(
        conn,
        item_id=candidate,
        reason="path coverage overlaps an active claim on 'main'",
        blocking_claim_id=blocking_claim,
        created_at=_now_iso(offset_minutes=-60 * 48),  # 48h ago
    )
    _add_dep_edge(conn, dependent=candidate, blocking=upstream)
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_pass_when_reason_does_not_mention_overlap(conn):
    candidate = 8301
    upstream = 8302
    blocking_claim = 9302
    _seed_path_claim(conn, claim_id=blocking_claim, item_id=upstream)
    _insert_blocked_event(
        conn,
        item_id=candidate,
        reason="actor_id 99 does not exist",
        blocking_claim_id=blocking_claim,
    )
    _add_dep_edge(conn, dependent=candidate, blocking=upstream)
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"


def test_pass_when_item_dependencies_missing(conn):
    # Drop the table to simulate a minimal-fixture environment.
    conn.execute("DROP TABLE item_dependencies")
    conn.commit()
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"

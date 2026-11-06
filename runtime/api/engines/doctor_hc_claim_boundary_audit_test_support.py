# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.path_context_test_support import _p as _p

import json

import uuid

from pathlib import Path

from typing import Iterator

import pytest

from yoke_core.domain import db_backend

from yoke_core.domain import check_claim_boundary_audit_cutoff as _cutoff

from yoke_core.engines.doctor_hc_claim_boundary_audit import hc_claim_boundary_audit

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from runtime.api.fixtures import pg_testdb

from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture(autouse=True)
def _disable_event_id_cutoff(monkeypatch: pytest.MonkeyPatch):
    """Classifier-focused tests author synthetic events that auto-
    increment from id=1; the canonical residue cutoff would suppress
    them. The cutoff sibling module owns its own coverage in
    ``test_doctor_hc_claim_boundary_audit_cutoff``."""
    monkeypatch.setattr(_cutoff, "read_min_event_id_cutoff", lambda: 0)
    yield


def _add_event(
    conn,
    name: str,
    sid: str,
    item_id: int | None,
    context: dict,
    created_at: str = "2026-05-17T12:00:00Z",
) -> int:
    if item_id is not None:
        # The finding names the event's item by reference.
        from runtime.api.fixtures.backlog import insert_item

        seed_project_identities(conn)
        try:
            insert_item(conn, id=item_id, project_sequence=item_id, title="fixture")
        except Exception:  # noqa: BLE001 - a claim may have seeded it already
            conn.rollback()
    p = _p(conn)
    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_name": name,
        "session_id": sid,
        "context": context,
    }
    cur = conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, severity,"
        " event_kind, event_type, event_name, item_id, envelope, created_at)"
        f" VALUES ({p}, 'backend', {p}, 'INFO', 'lifecycle', 'function_call',"
        f" {p}, {p}, {p}, {p}) RETURNING id",
        (
            envelope["event_id"],
            sid,
            name,
            str(item_id) if item_id is not None else None,
            json.dumps(envelope),
            created_at,
        ),
    )
    conn.commit()
    return int(cur.fetchone()[0])


def _add_session(conn, sid: str) -> None:
    p = _p(conn)
    conn.execute(
        f"INSERT INTO harness_sessions (project_id, session_id, executor, provider, model, workspace, mode, offered_at, last_heartbeat) VALUES (1, {p}, 'claude-code', 'anthropic', 'claude-opus-4-7', '/tmp/ws', 'charge', '2026-05-17T11:00:00Z', '2026-05-17T11:00:00Z')",
        (sid,),
    )
    conn.commit()


def _add_claim(
    conn,
    sid: str,
    item_id: int,
    claimed_at: str = "2026-05-17T11:30:00Z",
    released_at: str | None = None,
) -> None:
    # The finding names the item by reference, so its row exists.
    from runtime.api.fixtures.backlog import insert_item

    seed_project_identities(conn)
    try:
        insert_item(conn, id=item_id, project_sequence=item_id, title="fixture")
    except Exception:  # noqa: BLE001 - the case may have seeded it already
        conn.rollback()
    p = _p(conn)
    conn.execute(
        f"INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, released_at) VALUES ({p}, 'item', {p}, {p}, {p}, {p})",
        (
            sid,
            make_item_target(item_id).scope_json(),
            claimed_at,
            claimed_at,
            released_at,
        ),
    )
    conn.commit()


def _sid(label: str) -> str:
    return f"{label * 8}-{label * 4}-{label * 4}-{label * 4}-{label * 12}"


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield {"conn": conn}
        finally:
            conn.close()


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_claim_boundary_audit(conn, DoctorArgs(), rec)
    return rec

"""Fixture + seed helpers for :mod:`test_doctor_hc_routed_ownership`.

Split out so the test file stays within the AGENTS.md file budget. Owns the
minimal HC table set, the backend-aware per-test ``conn`` fixture, and the
session/claim/item seed helpers the routed-ownership HC tests use. The HCs
read first-class claim/chain state (``work_claims.release_reason_intent``,
``harness_sessions.last_chain_step`` / ``last_checkpoint_at``) — no
``events`` table is provisioned, proving the cutover left no ledger read.
"""
# lint:no-tmp-runtime-import-check  (real Yoke checkout under /tmp worktree;
# this is an in-tree test module, not an ad-hoc /tmp script — imports resolve
# from the worktree package root, mirroring routed_ownership_test_helpers.py)

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL DEFAULT 'claude-code',
    provider TEXT NOT NULL DEFAULT 'anthropic',
    model TEXT NOT NULL DEFAULT '',
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT,
    workspace TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL DEFAULT '',
    last_heartbeat TEXT NOT NULL DEFAULT '',
    ended_at TEXT,
    offer_envelope TEXT,
    actor_id INTEGER,
    last_chain_step INTEGER,
    last_checkpoint_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive',
    claimed_at TEXT NOT NULL DEFAULT '',
    last_heartbeat TEXT NOT NULL DEFAULT '',
    released_at TEXT,
    release_reason TEXT,
    reason TEXT,
    reason_intent TEXT,
    release_reason_intent TEXT
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idea'
);
"""


def _apply_schema() -> None:
    """``init_test_db`` ``apply_schema`` strategy for this HC family.

    Builds the minimal table set (``harness_sessions``, ``work_claims``,
    ``items``) the routed-ownership HCs and the underlying
    ``routed_ownership_exclusions`` defense read — deliberately NOT the full
    production schema. Resolves its own connection through the backend factory
    with ``YOKE_PG_DSN`` repointed to a disposable per-test Postgres database,
    so each test gets an isolated table set that never collides with the ambient
    production relations under ``-n``.
    """
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _iso(delta_s: int = 0) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


@pytest.fixture
def conn(tmp_path):
    """Postgres-backed per-test DB with the minimal HC table set applied.

    ``YOKE_PG_DSN`` is repointed for the context's lifetime so the
    code-under-test reads the one per-test DB the fixture seeded.
    """
    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _insert_session(
    conn: Any,
    session_id: str,
    *,
    heartbeat_age_s: int = 10,
    ended: bool = False,
    offer_envelope: Optional[dict] = None,
    last_chain_step: Optional[int] = None,
    last_checkpoint_at: Optional[str] = None,
) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, workspace, offered_at, "
        " last_heartbeat, ended_at, offer_envelope, last_chain_step, "
        " last_checkpoint_at) "
        f"VALUES ({p}, 'claude-code', 'anthropic', '/tmp', {p}, {p}, {p}, "
        f"{p}, {p}, {p})",
        (
            session_id,
            _iso(-heartbeat_age_s),
            _iso(-heartbeat_age_s),
            _iso() if ended else None,
            json.dumps(offer_envelope) if offer_envelope is not None else None,
            last_chain_step,
            last_checkpoint_at,
        ),
    )
    conn.commit()


def _insert_released_claim(
    conn: Any,
    session_id: str,
    item_id: int,
    *,
    released_age_s: int = 10,
    release_reason: str = "released",
    release_reason_intent: Optional[str] = None,
) -> int:
    p = _p(conn)
    row = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, claim_type, claimed_at, "
        " last_heartbeat, released_at, release_reason, "
        " release_reason_intent) "
        f"VALUES ({p}, 'item', {p}, 'exclusive', {p}, {p}, {p}, {p}, {p}) "
        "RETURNING id",
        (
            session_id,
            item_id,
            _iso(-released_age_s - 60),
            _iso(-released_age_s),
            _iso(-released_age_s),
            release_reason,
            release_reason_intent,
        ),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _insert_item(conn: Any, item_id: int, status: str) -> None:
    p = _p(conn)
    conn.execute(
        f"INSERT INTO items (id, status) VALUES ({p}, {p})",
        (item_id, status),
    )
    conn.commit()


def _run(hc, conn) -> RecordCollector:
    rec = RecordCollector()
    hc(conn, DoctorArgs(), rec)
    return rec


__all__ = [
    "conn",
    "_apply_schema",
    "_iso",
    "_insert_session",
    "_insert_released_claim",
    "_insert_item",
    "_run",
]

"""Shared schema strings, scheduler_db fixture, and SML helpers used by
the scheduler test sibling modules. Imported, not pytest-collected."""
from __future__ import annotations

import os

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,
    PROJECTS_SCHEMA,
)


HARNESS_SESSIONS_SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT,
    workspace TEXT,
    mode TEXT NOT NULL DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    current_item_id TEXT DEFAULT NULL,
    current_item_set_at TEXT DEFAULT NULL,
    recent_item_id TEXT DEFAULT NULL,
    recent_item_status TEXT DEFAULT NULL,
    recent_item_recorded_at TEXT DEFAULT NULL,
    actor_id INTEGER DEFAULT NULL
);
"""

WORK_CLAIMS_SCHEMA = """
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL,
    CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL)
    )
);
"""

EVENTS_SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT '',
    event_outcome TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    envelope TEXT NOT NULL DEFAULT '{}'
);
"""

# The scheduler's ``advance``-feasibility probe
# (``scheduler_path_claim_feasibility._fetch_candidate_claim``, reached via
# ``_compute_next_step``) reads ``path_claims``. When the table is absent the
# probe swallows the missing-relation error and returns NO_CLAIM — but on
# Postgres the failed read aborts the surrounding transaction, so the probe
# must ``conn.rollback()`` to leave the connection usable. That rollback
# silently discards any uncommitted row the test seeded before calling
# ``compute_schedule`` (e.g. an as-yet-uncommitted ``harness_sessions`` row).
# Including an (empty) ``path_claims`` table makes the probe return NO_CLAIM
# cleanly without the rollback. The probe only reads these columns and never
# seeds rows here, so the minimal shape suffices.
PATH_CLAIMS_SCHEMA = """
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'planned',
    mode TEXT NOT NULL DEFAULT 'exclusive',
    item_id INTEGER,
    integration_target TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL DEFAULT ''
);
"""

SCHEMA = (
    ITEMS_SCHEMA
    + ITEM_DEPENDENCIES_SCHEMA
    + HARNESS_SESSIONS_SCHEMA
    + WORK_CLAIMS_SCHEMA
    + PROJECTS_SCHEMA
    + EVENTS_SCHEMA
    + PATH_CLAIMS_SCHEMA
)


def _item_num(item_id) -> int:
    """Strip a ``YOK-N`` prefix and return the bare integer.

    ``work_claims.item_id`` is an integer column; ``compute_schedule`` and
    ``selected_step.item_id`` surface the display form ``YOK-N``. SQLite's
    dynamic typing tolerated inserting the ``YOK-N`` string directly, but
    Postgres's integer column rejects it (``invalid input syntax for type
    integer``). Tests strip the prefix here before writing to the integer
    column; the production read path (``scheduler_claims._evaluate_claim_states``)
    reconstructs the ``YOK-N`` display key from the bare integer.
    """
    text = str(item_id)
    if text.upper().startswith("YOK-"):
        text = text[4:]
    return int(text)


def _apply_scheduler_schema() -> None:
    """``apply_schema`` strategy that builds the scheduler-test ``SCHEMA``.

    Resolves its own connection through the backend factory with
    ``YOKE_PG_DSN`` repointed to the disposable per-test Postgres database.
    The fixture DDL helper strips cross-family FK clauses for native Postgres;
    scheduler tests no longer require SQLite-shaped schema introspection shims.
    """
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def scheduler_db(tmp_path):
    """Create a temporary DB with all tables needed for scheduler tests.

    ``YOKE_PG_DSN`` is repointed to a disposable per-test Postgres database
    for the fixture's lifetime, then restored and dropped on teardown. The
    yielded ``tmp_dir`` is the workspace root for the SML helpers.
    """
    tmp_dir = str(tmp_path)
    with init_test_db(tmp_path, apply_schema=_apply_scheduler_schema) as db_path:
        conn = connect_test_db(db_path)
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"

        # Seed items: different types and statuses for type-aware routing
        # Statuses use the canonical lifecycle
        items = [
            (1, "Refined issue", "issue", "refined-idea", "high"),
            (2, "Idea issue", "issue", "idea", "medium"),
            (3, "Idea epic", "epic", "idea", "high"),
            (4, "Implementing issue", "issue", "implementing", "medium"),
            (5, "Implemented issue", "issue", "implemented", "low"),
            (6, "Blocked issue", "issue", "blocked", "medium"),
            (7, "Done issue", "issue", "done", "high"),
            (8, "Refined epic", "epic", "refined-idea", "medium"),
        ]
        for item_id, title, item_type, status, priority in items:
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority, project_id,
                    project_sequence, created_at, updated_at, source, frozen)
                   VALUES ({p}, {p}, {p}, {p}, {p}, 1,
                           {p}, '2026-03-01', '2026-03-01', 'user', 0)""".format(p=p),
                (item_id, title, item_type, status, priority, item_id),
            )

        conn.commit()

        try:
            yield {"conn": conn, "db_path": db_path, "tmp_dir": tmp_dir}
        finally:
            conn.close()


def _create_sml_files(tmp_dir):
    """Create SML files in the workspace with future timestamps."""
    strategy_dir = os.path.join(tmp_dir, ".yoke", "strategy")
    os.makedirs(strategy_dir, exist_ok=True)
    for fname in ("MISSION.md", "LANDSCAPE.md", "VISION.md", "MASTER-PLAN.md"):
        fpath = os.path.join(strategy_dir, fname)
        with open(fpath, "w") as f:
            f.write(f"# {fname}\n")
        os.utime(fpath, (9999999999, 9999999999))

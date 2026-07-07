"""Shared helpers for the observe pytest suites.

Split out of the original ``test_observe.py`` so each authored test file
stays under the 350-line limit. Lives outside the ``test_*.py`` collection
pattern so pytest does not pick it up as a test module.

The DB fixtures route through
:func:`runtime.api.fixtures.file_test_db.init_test_db` so the test bodies run
against the ``db_backend``-selected authority instead of a raw SQLite file. The
legacy fixtures created a ``tempfile`` SQLite file with a hand-rolled
``events`` / ``items`` / ``harness_sessions`` schema and bypassed
``db_backend`` entirely. Routing through ``init_test_db`` provisions a
disposable per-test Postgres database (``YOKE_PG_DSN`` repointed for the
block) so the production read path is exercised on the real authority.

* :func:`observe_events_db` - events-table-bearing per-test DB; production
  ``insert_event`` writes through the connection the test opens with
  ``connect_test_db``.
* :func:`observe_attribution_db` - roots the per-test DB at
  ``<project_dir>/data/yoke.db`` so ``repo_root_for_attribution`` resolves the
  repo root from the path shape while reads route through the backend factory.
  :func:`seed_item` and :func:`seed_session` populate the canonical schema
  columns the ``SCHEMA_DDL`` fixture creates.
"""

from __future__ import annotations

import contextlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Tuple

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import apply_fixture_schema_ddl, init_test_db


def _fresh_now() -> str:
    """Return a fresh ISO 8601 UTC timestamp for freshness-sensitive session fixtures."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@contextlib.contextmanager
def observe_events_db() -> Iterator[str]:
    """Yield a backend-appropriate ``db_path`` with the fixture schema applied.

    Postgres gets a disposable per-test database with ``YOKE_PG_DSN``
    repointed for the block. The schema comes from ``apply_fixture_schema_ddl``
    (the canonical ``SCHEMA_DDL`` fixture, which includes the ``events`` table
    unlike ``schema.cmd_init``), so ``insert_event`` writes the same columns it
    writes in production.
    """
    with tempfile.TemporaryDirectory() as td:
        with init_test_db(Path(td), apply_schema=apply_fixture_schema_ddl) as db_path:
            yield db_path


@contextlib.contextmanager
def observe_attribution_db() -> Iterator[Tuple[str, str]]:
    """Yield ``(db_path, project_dir)`` for main-session attribution tests.

    The token is rooted at ``<project_dir>/data/yoke.db`` so
    ``repo_root_for_attribution`` resolves ``project_dir`` from the path shape
    (not file existence). The path is an ignored placeholder; reads route to the
    per-test database through the backend factory.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        data_dir = root / "data"
        data_dir.mkdir()
        with init_test_db(data_dir, apply_schema=apply_fixture_schema_ddl) as db_path:
            yield db_path, str(root)


def seed_item(conn, item_id: int, *, status: str, item_type: str = "issue") -> None:
    """Insert one ``items`` row with the canonical NOT NULL columns populated.

    Attribution only reads ``id`` / ``status`` / ``type``; the remaining NOT NULL
    columns carry deterministic fixture values.
    """
    now = "2026-01-01T00:00:00Z"
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, flow, "
        "rework_count, frozen, created_at, updated_at, source, "
        "project_id, project_sequence) "
        f"VALUES ({p}, {p}, {p}, {p}, 'medium', 'accelerated', 0, 0, "
        f"{p}, {p}, 'test', 1, {p})",
        (item_id, f"Item {item_id}", item_type, status, now, now, item_id),
    )


def seed_session(
    conn,
    session_id: str,
    *,
    current_item_id: Optional[str] = None,
    current_item_set_at: Optional[str] = None,
    recent_item_id: Optional[str] = None,
    recent_item_recorded_at: Optional[str] = None,
) -> None:
    """Insert one ``harness_sessions`` row with the canonical NOT NULL columns.

    The attribution reader only consults ``current_item_id`` / ``recent_item_id``
    / ``recent_item_recorded_at``; the remaining NOT NULL columns carry
    deterministic fixture values.
    """
    now = _fresh_now()
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, offered_at, "
        "last_heartbeat, current_item_id, current_item_set_at, recent_item_id, "
        "recent_item_recorded_at) "
        f"VALUES ({p}, 'test', 'test', 'test', '/tmp', {p}, {p}, {p}, {p}, {p}, {p})",
        (
            session_id,
            now,
            now,
            current_item_id,
            current_item_set_at,
            recent_item_id,
            recent_item_recorded_at,
        ),
    )

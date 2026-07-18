"""Shared frontier DB fixture/helper for the api-deploy test suite."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.api.main import app, get_db_path, get_db_readonly, get_db_readwrite


# ---------------------------------------------------------------------------
# Frontier DB helpers
# ---------------------------------------------------------------------------


def _seed_frontier_conn(conn) -> None:
    """Seed the current Postgres test DB with frontier rows."""
    conn.execute("DELETE FROM item_dependencies")
    conn.execute("DELETE FROM items")

    # Item 20: active (conduct-eligible), high priority, yoke
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (20, 'Active task', 'issue', 'implementing', 'high', 1, 20, 0,
                   '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user')"""
    )
    # Item 21: idea (shepherd-eligible), medium priority, yoke.
    # Populate spec so frontier_compute's idea-body completeness check
    # treats this as a real, runnable idea rather than a title-only draft.
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source, spec)
           VALUES (21, 'Idea task', 'issue', 'idea', 'medium', 1, 21, 0,
                   '2026-03-01T00:00:00Z', '2026-03-03T00:00:00Z', 'user',
                   '# Idea task\n\nFixture spec body for frontier tests.')"""
    )
    # Item 22: idea, blocked by an unlisted activation blocker, yoke.
    # Populate spec so the body-completeness check does not double-classify
    # this row; the activation-blocker dependency is what should put it in
    # the blocked bucket.
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source, spec)
           VALUES (22, 'Blocked idea', 'issue', 'idea', 'low', 1, 22, 0,
                   '2026-03-01T00:00:00Z', '2026-03-04T00:00:00Z', 'user',
                   '# Blocked idea\n\nFixture spec body for frontier tests.')"""
    )
    conn.execute(
        """INSERT INTO item_dependencies
           (dependent_item, blocking_item, gate_point, satisfaction, source, rationale, created_at)
           VALUES ('YOK-22', 'YOK-20', 'activation', 'status:done', 'shepherd', 'YOK-22 depends on YOK-20', '2026-03-01T00:00:00Z')"""
    )
    # Item 23: done, yoke (terminal — excluded from frontier)
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (23, 'Done task', 'issue', 'done', 'medium', 1, 23, 0,
                   '2026-03-01T00:00:00Z', '2026-03-05T00:00:00Z', 'user')"""
    )
    # Item 24: ready, externalwebapp project (different project)
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (24, 'ExternalWebapp ready', 'issue', 'refined-idea', 'high', 2, 24, 0,
                   '2026-03-01T00:00:00Z', '2026-03-06T00:00:00Z', 'user')"""
    )
    # Item 25: frozen item, yoke
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (25, 'Frozen task', 'issue', 'refined-idea', 'high', 1, 25, 1,
                   '2026-03-01T00:00:00Z', '2026-03-07T00:00:00Z', 'user')"""
    )
    # Item 26: passed item, yoke (usher-eligible and still on the frontier)
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (26, 'Passed task', 'issue', 'implemented', 'high', 1, 26, 0,
                   '2026-03-01T00:00:00Z', '2026-03-08T00:00:00Z', 'user')"""
    )
    # Item 27: explicit blocked item, yoke (reported in blocked bucket)
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence, frozen,
            created_at, updated_at, source)
           VALUES (27, 'Explicitly blocked task', 'issue', 'blocked', 'medium', 1, 27, 0,
                   '2026-03-01T00:00:00Z', '2026-03-09T00:00:00Z', 'user')"""
    )

    conn.commit()


@pytest.fixture()
def frontier_db():
    """Fixture for frontier endpoint tests."""
    from runtime.api.fixtures.pg_testdb import test_database

    pg_db = test_database()
    seed_conn = pg_db.__enter__()
    _seed_frontier_conn(seed_conn)
    auth = mint_api_auth_context(seed_conn)

    def _override_db_path() -> str:
        return ""

    def _override_db_readonly():
        return db_backend.connect()

    def _override_db_readwrite():
        return db_backend.connect()

    app.dependency_overrides[get_db_path] = _override_db_path
    app.dependency_overrides[get_db_readonly] = _override_db_readonly
    app.dependency_overrides[get_db_readwrite] = _override_db_readwrite

    try:
        with patch("yoke_core.api.main.get_db_path", _override_db_path), \
             patch("yoke_core.api.main.get_db_readonly", _override_db_readonly), \
             patch("yoke_core.api.main.get_db_readwrite", _override_db_readwrite):
            yield {
                "db_path": "",
                "pg_dsn": os.environ.get(db_backend.PG_DSN_ENV, ""),
                "auth_headers": auth.headers,
            }
    finally:
        app.dependency_overrides.clear()
        pg_db.__exit__(None, None, None)

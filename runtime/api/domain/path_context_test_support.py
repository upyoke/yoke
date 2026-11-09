# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, path_context

from yoke_core.domain.agents_render import AGENTS

from yoke_core.domain.agents_render_conditional import (
    HARNESS_IDS,
    rendered_agent_path,
)

from yoke_core.domain.agents_render_path_context import (
    read_render_source_for,
    record_render_relationships,
    render_relationship_map,
    set_render_relationship,
)

from yoke_core.domain.event_catalog_render import EVENT_CATALOG_RELPATH

from yoke_core.domain.schema_events import ensure_event_schema

from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
    create_path_integrity_tables,
    create_path_registry_tables,
)

from yoke_core.tools.atlas_render_docs import ATLAS_RELPATH

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_path_context_schema() -> None:
    """Build the render-relationship schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, "
            "default_branch TEXT NOT NULL DEFAULT 'main', "
            "github_repo TEXT, public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TIMESTAMPTZ NOT NULL)"
        )
        create_core_tables(conn)
        create_governed_tables(conn)
        ensure_event_schema(conn)
        create_path_registry_tables(conn)
        create_path_integrity_tables(conn)
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at) "
            "VALUES (1, 'yoke', 'yoke', '2026-05-01T00:00:00Z') "
            "ON CONFLICT DO NOTHING"
        )
        conn.commit()
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_target(conn, *, path_string: str) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        f"VALUES (1, 'file', {p}, 1, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    return int(cur.fetchone()[0])


@pytest.fixture
def fresh_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=_apply_path_context_schema) as path:
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()

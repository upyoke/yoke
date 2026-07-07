"""Shared Postgres-backed fixtures for path-integrity tests."""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_core.domain.events_schema import _create_events_table
from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
    create_path_integrity_tables,
    create_path_registry_tables,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def apply_path_integrity_schema() -> None:
    """Build the path-integrity schema on the active test backend."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, emoji TEXT DEFAULT '', "
            "default_branch TEXT NOT NULL DEFAULT 'main', "
            "github_repo TEXT, public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        create_core_tables(conn)
        seed_project_identities(conn)
        create_governed_tables(conn)
        _create_events_table(conn)
        create_path_registry_tables(conn)
        create_path_integrity_tables(conn)
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def path_integrity_db(tmp_path: Path):
    """Yield a backend-aware connection with the path-integrity schema."""
    with init_test_db(tmp_path, apply_schema=apply_path_integrity_schema) as path:
        conn = connect_test_db(path)
        try:
            yield conn
        finally:
            conn.close()


__all__ = ["apply_path_integrity_schema", "path_integrity_db"]

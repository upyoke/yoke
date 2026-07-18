"""Backend-aware fixtures for path-snapshot tests."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from yoke_core.domain import db_backend
from yoke_core.domain.events_schema import _create_events_table
from yoke_core.domain.schema_init_tables import create_path_registry_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout

NOW = "2026-04-29T00:00:00Z"


def _project_row_id(project_id: str | int) -> int:
    text = str(project_id)
    if text.isdigit():
        return int(text)
    return {"yoke": 1, "externalwebapp": 2, "demo": 3, "p": 4}.get(text, 100)


def _apply_path_snapshot_schema(
    repo_path: Path | None,
    project_id: str | int | None,
    config_root: Path,
) -> None:
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, "
            "default_branch TEXT NOT NULL DEFAULT 'main', github_repo TEXT, "
            "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
            "created_at TEXT NOT NULL)"
        )
        if project_id is not None and repo_path is not None:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            numeric_project_id = _project_row_id(project_id)
            slug = str(project_id) if not str(project_id).isdigit() else f"project-{project_id}"
            # config_root is a per-test temp dir — repo_path may be the LIVE
            # yoke checkout (the Yoke-repo perf test), whose .parent is the real
            # .worktrees/ and would be polluted by a config write there.
            register_machine_checkout(config_root, repo_path, numeric_project_id)
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, created_at) "
                f"VALUES ({p}, {p}, {p}, {p})",
                (numeric_project_id, slug, slug, NOW),
            )
        _create_events_table(conn)
        create_path_registry_tables(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def path_snapshot_db(
    tmp_path: Path,
    repo_path: Path | None,
    *,
    project_id: str | None = "demo",
) -> Iterator:
    """Yield a backend-routed DB for path-snapshot tests."""

    def apply_schema() -> None:
        _apply_path_snapshot_schema(
            repo_path, project_id, tmp_path / "machine-config"
        )

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()

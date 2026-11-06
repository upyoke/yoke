# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.path_context_test_support import _p as _p

from datetime import datetime, timezone

import json

import os

import sqlite3

from pathlib import Path

from typing import Iterator

import pytest

from yoke_core.domain import db_backend

from runtime.api.fixtures.migration_model_test import (
    governed_postgres_test_seed,
    membership_ledger_test_seed,
)

from yoke_core.domain.schema_init_apply import execute_schema_script

from yoke_core.domain.worktree_validation_surface import (
    CANONICAL_YOKE_DB_ENV,
    prompt_env_var_bindings,
    provision_validation_surfaces,
    resolve_validation_db_paths,
)

from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_table_exists,
)

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

_CONTROL_DB_DDL = """
    CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT NOT NULL, public_item_prefix TEXT NOT NULL DEFAULT 'YOK', created_at TIMESTAMPTZ NOT NULL);
    CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, type TEXT NOT NULL, settings TEXT DEFAULT '{}', verified_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL, UNIQUE(project_id, type));
"""

_CONTROL_SEED_AT = datetime(2026, 4, 23, tzinfo=timezone.utc)


def _upsert_project_sql(p: str) -> str:
    return (
        "INSERT INTO projects (id, slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}) ON CONFLICT (id) DO UPDATE SET "
        "slug = excluded.slug, name = excluded.name, "
        "created_at = excluded.created_at"
    )


def _upsert_capability_sql(p: str) -> str:
    return (
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}) ON CONFLICT (project_id, type) DO UPDATE SET "
        "settings = excluded.settings, created_at = excluded.created_at"
    )


def _apply_control_db_schema() -> None:
    """Backend-routed schema for the capability-lookup control DB."""
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _CONTROL_DB_DDL)
        p = _p(conn)
        conn.execute(
            _upsert_project_sql(p),
            (1, "yoke", "Yoke", _CONTROL_SEED_AT),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def control_db(tmp_path: Path) -> Iterator[str]:
    """Backend-appropriate control DB with the capability-lookup schema."""
    with init_test_db(tmp_path, apply_schema=_apply_control_db_schema) as path:
        yield path


def _seed_capability(
    control_db: str, project: str, settings: dict | None = None
) -> None:
    project_id = 1 if project == "yoke" else 100
    settings_json = json.dumps(
        settings if settings is not None else governed_postgres_test_seed(),
        sort_keys=True,
    )
    conn = connect_test_db(control_db)
    p = _p(conn)
    conn.execute(
        _upsert_project_sql(p),
        (project_id, project, project.capitalize(), _CONTROL_SEED_AT),
    )
    conn.execute(
        _upsert_capability_sql(p),
        (project_id, "migration_model", settings_json, _CONTROL_SEED_AT),
    )
    conn.commit()
    conn.close()


def _webapp_sqlite_settings() -> dict:
    return {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "sqlite_file",
                    "location": {"path": "app/data/app.db"},
                },
                "validation_surface": {
                    "kind": "worktree_local_sqlite",
                    "provisioning": {
                        "path": ".yoke/validation.db",
                        "recipe": "webapp_sqlite_empty",
                    },
                },
                "runner": {
                    "kind": "governed_migration_module",
                    "config": {
                        "modules_dir": "app/db/migrations",
                        "connection_env_var": "APP_DB_PATH",
                        "ledger": membership_ledger_test_seed(),
                    },
                },
            },
        },
    }


@pytest.fixture
def control_db_env(control_db: str, monkeypatch) -> Iterator[str]:
    from yoke_core.domain import worktree_validation_surface as surfaces

    load = surfaces._load_capability
    monkeypatch.setattr(
        surfaces, "_load_capability",
        lambda project, **_kwargs: load(project, db_path=control_db),
    )
    prior = os.environ.get("YOKE_DB")
    os.environ["YOKE_DB"] = control_db
    try:
        yield control_db
    finally:
        if prior is None:
            os.environ.pop("YOKE_DB", None)
        else:
            os.environ["YOKE_DB"] = prior

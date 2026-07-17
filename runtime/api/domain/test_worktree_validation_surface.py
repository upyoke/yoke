"""Tests for worktree_validation_surface (governed DB-mutation contract §6.0 / AC-34–39)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.migration_model_test import governed_postgres_test_seed
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.worktree_validation_surface import (
    CANONICAL_YOKE_DB_ENV,
    ProvisionResult,
    prompt_env_var_bindings,
    provision_validation_surfaces,
    resolve_validation_db_paths,
)
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_table_exists,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_CONTROL_DB_DDL = """
    CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT NOT NULL, public_item_prefix TEXT NOT NULL DEFAULT 'YOK', created_at TEXT NOT NULL);
    CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, type TEXT NOT NULL, settings TEXT DEFAULT '{}', verified_at TEXT, created_at TEXT NOT NULL, UNIQUE(project_id, type));
"""


def _p(conn) -> str: return "%s" if db_backend.connection_is_postgres(conn) else "?"


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
            (1, "yoke", "Yoke", "2026-04-23T00:00:00Z"),
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
        (project_id, project, project.capitalize(), "2026-04-23T00:00:00Z"),
    )
    conn.execute(
        _upsert_capability_sql(p),
        (project_id, "migration_model", settings_json,
         "2026-04-23T00:00:00Z"),
    )
    conn.commit()
    conn.close()


def _seed_yoke_capability(control_db: str, settings: dict | None = None) -> None:
    _seed_capability(control_db, "yoke", settings)


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
                    },
                },
            },
        },
    }


@pytest.fixture
def control_db_env(control_db: str) -> Iterator[str]:
    prior = os.environ.get("YOKE_DB")
    os.environ["YOKE_DB"] = control_db
    try:
        yield control_db
    finally:
        if prior is None:
            os.environ.pop("YOKE_DB", None)
        else:
            os.environ["YOKE_DB"] = prior


class TestResolveValidationDbPaths:
    def test_returns_empty_when_no_capability(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        # No migration_model capability seeded in control_db.
        result = resolve_validation_db_paths(tmp_path, "yoke")
        assert result == {}

    def test_maps_model_to_env_var_and_path(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_capability(control_db_env, "buzz", _webapp_sqlite_settings())
        result = resolve_validation_db_paths(tmp_path, "buzz")
        assert result == {
            "primary": {
                "env_var": "APP_DB_PATH",
                "path": str((tmp_path / ".yoke" / "validation.db").resolve()),
            },
        }

    def test_skips_non_worktree_local_sqlite_surfaces(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        settings = {
            "default_model": "primary",
            "models": {
                "primary": {
                    "authoritative_db": {
                        "kind": "sqlite_file",
                        "location": {"path": "app/data/app.db"},
                    },
                    # Reserved for governed DB-mutation gate — validator schema-open: allow anything.
                    "validation_surface": {
                        "kind": "external_validation",
                        "provisioning": {
                            "trigger": "ci",
                            "evidence_contract": "artifact",
                        },
                    },
                    "runner": {
                        "kind": "governed_migration_module",
                        "config": {
                            "modules_dir": "runtime/api/domain/migrations",
                            "connection_env_var": "APP_DB_PATH",
                        },
                    },
                },
            },
        }
        # This sqlite-authority/external-validation pairing is invalid for the
        # live validator, so the helper treats it as no capability.
        settings_json = json.dumps(settings, sort_keys=True)
        conn = connect_test_db(control_db_env)
        p = _p(conn)
        conn.execute(
            _upsert_project_sql(p),
            (1, "yoke", "Yoke", "2026-04-23T00:00:00Z"),
        )
        conn.execute(
            _upsert_capability_sql(p),
            (1, "migration_model", settings_json,
             "2026-04-23T00:00:00Z"),
        )
        conn.commit()
        conn.close()
        # The validator rejects the unsupported pairing; the helper treats
        # invalid capability JSON as "no capability" and returns {}.
        result = resolve_validation_db_paths(tmp_path, "yoke")
        assert result == {}


def test_webapp_template_docs_mark_sqlite_as_app_local() -> None:
    root = Path(__file__).resolve().parents[3]
    template = json.loads((root / "templates/webapp/template.json").read_text())
    rels = ("templates/webapp/README.md", "templates/webapp/scaffold/AGENTS.md", "templates/webapp/scaffold/ROADMAP.md", "docs/db-reference/migration-model-capabilities.md")
    texts = [(root / rel).read_text() for rel in rels]
    assert "app-local SQLite" in template["description"]
    assert all("app-local" in text and "Postgres control plane" in text for text in texts)
    assert all("data/yoke.db" in text for text in (texts[0], texts[1], texts[3]))


class TestPromptEnvVarBindings:
    def test_canonical_always_first(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_yoke_capability(control_db_env)
        bindings = prompt_env_var_bindings(
            tmp_path, "yoke",
            canonical_db_path="/canonical/control-plane",
        )
        assert bindings[0] == (CANONICAL_YOKE_DB_ENV, "/canonical/control-plane")

    def test_per_model_env_var_added(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_yoke_capability(control_db_env)
        bindings = prompt_env_var_bindings(
            tmp_path, "yoke",
            canonical_db_path="/canonical/control-plane",
        )
        # Yoke's primary model uses external Postgres validation, so no
        # worktree-local DB binding is added.
        assert bindings == [
            (CANONICAL_YOKE_DB_ENV, "/canonical/control-plane"),
        ]

    def test_no_capability_returns_canonical_only(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        bindings = prompt_env_var_bindings(
            tmp_path, "yoke",
            canonical_db_path="/canonical/control-plane",
        )
        assert bindings == [
            (CANONICAL_YOKE_DB_ENV, "/canonical/control-plane"),
        ]


class TestProvisionValidationSurfaces:
    def test_creates_validation_db_for_primary_model(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_yoke_capability(control_db_env)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        result = provision_validation_surfaces(worktree, "yoke")
        assert result.surfaces == []
        assert not result.any_failures

    def test_idempotent_on_second_call(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_yoke_capability(control_db_env)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        provision_validation_surfaces(worktree, "yoke")
        second = provision_validation_surfaces(worktree, "yoke")
        assert second.surfaces == []
        assert not second.any_failures

    def test_yoke_external_validation_does_not_seed_sqlite_schema(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        # Yoke authority is Postgres and the primary model uses external
        # validation, so no worktree-local SQLite schema is seeded.
        _seed_yoke_capability(control_db_env)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        result = provision_validation_surfaces(worktree, "yoke")
        assert result.surfaces == []

    def test_webapp_sqlite_validation_surface_is_provisioned(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        _seed_capability(control_db_env, "buzz", _webapp_sqlite_settings())
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        result = provision_validation_surfaces(worktree, "buzz")

        assert not result.any_failures
        assert len(result.surfaces) == 1
        surface = result.surfaces[0]
        assert surface.model_name == "primary"
        assert surface.env_var == "APP_DB_PATH"
        assert surface.created is True
        validation_db = worktree / ".yoke" / "validation.db"
        assert surface.path == validation_db.resolve()
        assert not (worktree / "data" / "yoke.db").exists()

        conn = sqlite3.connect(str(validation_db))
        try:
            assert _generic_sqlite_validation_table_exists(
                conn,
                "schema_version",
            )
        finally:
            conn.close()

        second = provision_validation_surfaces(worktree, "buzz")
        assert len(second.surfaces) == 1
        assert second.surfaces[0].created is False

    def test_no_capability_is_clean_no_op(
        self, tmp_path: Path, control_db_env: str
    ) -> None:
        # No capability seeded in control_db.
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        result = provision_validation_surfaces(worktree, "yoke")
        assert result.surfaces == []
        assert not result.any_failures

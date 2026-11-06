"""Tests for worktree_validation_surface (governed DB-mutation contract)."""

from __future__ import annotations

from runtime.api.domain.worktree_validation_surface_test_support import (_CONTROL_DB_DDL as _CONTROL_DB_DDL, _CONTROL_SEED_AT as _CONTROL_SEED_AT, _apply_control_db_schema as _apply_control_db_schema, _seed_capability as _seed_capability, _upsert_capability_sql as _upsert_capability_sql, _upsert_project_sql as _upsert_project_sql, _webapp_sqlite_settings as _webapp_sqlite_settings, control_db as control_db, control_db_env as control_db_env)
from runtime.api.domain.path_context_test_support import (_p as _p)


import json
import pytest
import sqlite3
from pathlib import Path


from yoke_core.domain.worktree_validation_surface import (
    CANONICAL_YOKE_DB_ENV,
    prompt_env_var_bindings,
    provision_validation_surfaces,
    resolve_validation_db_paths,
)
from yoke_core.domain.schema_common_sqlite_validation import (
    _generic_sqlite_validation_table_exists,
)
from runtime.api.fixtures.file_test_db import connect_test_db


def _seed_yoke_capability(control_db: str, settings: dict | None = None) -> None:
    _seed_capability(control_db, "yoke", settings)


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
        _seed_capability(control_db_env, "externalwebapp", _webapp_sqlite_settings())
        result = resolve_validation_db_paths(tmp_path, "externalwebapp")
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
            (1, "yoke", "Yoke", _CONTROL_SEED_AT),
        )
        conn.execute(
            _upsert_capability_sql(p),
            (1, "migration_model", settings_json, _CONTROL_SEED_AT),
        )
        conn.commit()
        conn.close()
        with pytest.raises(RuntimeError, match="validation_capability_invalid"):
            resolve_validation_db_paths(tmp_path, "yoke")


class TestPromptEnvVarBindings:
    def test_canonical_always_first(self, tmp_path: Path, control_db_env: str) -> None:
        _seed_yoke_capability(control_db_env)
        bindings = prompt_env_var_bindings(
            tmp_path,
            "yoke",
            canonical_db_path="/canonical/control-plane",
        )
        assert bindings[0] == (CANONICAL_YOKE_DB_ENV, "/canonical/control-plane")

    def test_per_model_env_var_added(self, tmp_path: Path, control_db_env: str) -> None:
        _seed_yoke_capability(control_db_env)
        bindings = prompt_env_var_bindings(
            tmp_path,
            "yoke",
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
            tmp_path,
            "yoke",
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
        _seed_capability(control_db_env, "externalwebapp", _webapp_sqlite_settings())
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        result = provision_validation_surfaces(worktree, "externalwebapp")

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

        second = provision_validation_surfaces(worktree, "externalwebapp")
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

"""Validator coverage for the webapp recipe + Python module runner.

Split out from ``test_migration_model_capability.py`` to keep both
files under the 350-line cap. The helpers are duplicated rather than
imported because the sibling test file already houses its own
``_minimal_sqlite_model``; copying the small builder keeps the test
modules independent.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.migration_model_capability import (
    MigrationModelCapabilityError,
    validate,
)


def _minimal_sqlite_model(**overrides):
    base = {
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
    }
    base.update(overrides)
    return base


def _webapp_validation_surface() -> dict:
    return {
        "kind": "worktree_local_sqlite",
        "provisioning": {
            "path": ".yoke/validation.db",
            "recipe": "webapp_sqlite_empty",
        },
    }


class TestWebappValidationRecipe:
    def test_unknown_recipe_rejected(self) -> None:
        # Unknown recipe names fail closed at validation time.
        model = _minimal_sqlite_model(
            validation_surface={
                "kind": "worktree_local_sqlite",
                "provisioning": {
                    "path": ".yoke/validation.db",
                    "recipe": "nonexistent_recipe",
                },
            },
        )
        with pytest.raises(MigrationModelCapabilityError, match="recipe"):
            validate({"models": {"primary": model}})

    def test_webapp_recipe_accepted(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface=_webapp_validation_surface(),
            runner={
                "kind": "governed_migration_module",
                "config": {
                    "modules_dir": "app/db/migrations",
                    "connection_env_var": "APP_DB_PATH",
                },
            },
        )
        out = validate({"models": {"primary": model}})
        assert (
            out["models"]["primary"]["validation_surface"]
            ["provisioning"]["recipe"] == "webapp_sqlite_empty"
        )


class TestWebappPythonRunner:
    def test_governed_migration_module_accepted_for_webapp(self) -> None:
        # Webapp / ExternalWebapp uses the same Python migration-module runner as Yoke;
        # only the configured modules dir and connection env var differ.
        model = _minimal_sqlite_model(
            validation_surface=_webapp_validation_surface(),
            runner={
                "kind": "governed_migration_module",
                "config": {
                    "modules_dir": "app/db/migrations",
                    "connection_env_var": "APP_DB_PATH",
                },
            },
        )
        out = validate({"models": {"primary": model}})
        runner = out["models"]["primary"]["runner"]
        assert runner["kind"] == "governed_migration_module"
        assert runner["config"]["modules_dir"] == "app/db/migrations"
        assert runner["config"]["connection_env_var"] == "APP_DB_PATH"

    def test_governed_migration_module_requires_modules_dir(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface=_webapp_validation_surface(),
            runner={
                "kind": "governed_migration_module",
                "config": {"connection_env_var": "APP_DB_PATH"},
            },
        )
        with pytest.raises(
            MigrationModelCapabilityError, match="modules_dir"
        ):
            validate({"models": {"primary": model}})

    def test_governed_migration_module_defaults_connection_env_var(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface=_webapp_validation_surface(),
            runner={
                "kind": "governed_migration_module",
                "config": {"modules_dir": "app/db/migrations"},
            },
        )
        out = validate({"models": {"primary": model}})
        assert (
            out["models"]["primary"]["runner"]["config"]["connection_env_var"]
            == "YOKE_PG_DSN"
        )

    def test_governed_migration_module_rejects_unknown_keys(self) -> None:
        model = _minimal_sqlite_model(
            validation_surface=_webapp_validation_surface(),
            runner={
                "kind": "governed_migration_module",
                "config": {
                    "modules_dir": "app/db/migrations",
                    "connection_env_var": "APP_DB_PATH",
                    "bogus_key": True,
                },
            },
        )
        with pytest.raises(
            MigrationModelCapabilityError, match="bogus_key"
        ):
            validate({"models": {"primary": model}})

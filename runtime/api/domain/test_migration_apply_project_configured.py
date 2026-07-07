"""Project-configured Python migration-module runner coverage.

Covers the intended YOK-1879 shape: the Python ``apply(conn)`` migration
runner Yoke already uses is project-configured and works for a webapp /
Buzz-style project by changing config paths, not by inventing a second
runner family.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import ModuleResolutionError
from yoke_core.domain.migration_apply_runners import (
    RUNNER_KIND_GOVERNED_MODULE,
    UnknownRunnerKind,
    dispatch_handle,
    known_runner_kinds,
)
from yoke_core.domain.migration_apply_resolve import default_worktree_path
from yoke_core.domain.migration_audit_schema import (
    ensure_migration_audit_table,
)
from yoke_core.domain.schema_common import _get_tables, _table_exists
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.worktree_validation_recipes import (
    RECIPE_WEBAPP_SQLITE_EMPTY,
    UnknownValidationRecipe,
    dispatch as dispatch_recipe,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.file_test_db import (
    connect_test_db,
    init_test_db,
)


def _webapp_python_model() -> dict:
    return {
        "authoritative_db": {
            "kind": "sqlite_file",
            "location": {"path": "app/data/app.db"},
        },
        "validation_surface": {
            "kind": "worktree_local_sqlite",
            "provisioning": {
                "path": ".yoke/validation.db",
                "recipe": RECIPE_WEBAPP_SQLITE_EMPTY,
            },
        },
        "runner": {
            "kind": RUNNER_KIND_GOVERNED_MODULE,
            "config": {
                "modules_dir": "app/db/migrations",
                "connection_env_var": "APP_DB_PATH",
            },
        },
    }


def _write_python_migration(repo_root: Path, slug: str, body: str) -> Path:
    modules_dir = repo_root / "app" / "db" / "migrations"
    modules_dir.mkdir(parents=True, exist_ok=True)
    target = modules_dir / f"{slug}.py"
    target.write_text(body)
    return target


def _apply_default_worktree_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(
            conn,
            "CREATE TABLE projects ("
            "id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
            "name TEXT, public_item_prefix TEXT DEFAULT 'YOK'); "
            "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER, "
            "project_sequence INTEGER, worktree TEXT);"
        )
        conn.commit()
    finally:
        conn.close()


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@contextlib.contextmanager
def _seeded_default_worktree_db(tmp_path: Path) -> Iterator[Any]:
    with init_test_db(tmp_path, apply_schema=_apply_default_worktree_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            p = _placeholder(conn)
            conn.execute(
                "INSERT INTO projects (id, slug, name) "
                f"VALUES ({p}, {p}, {p})",
                (2, "buzz", "Buzz"),
            )
            conn.execute(
                "INSERT INTO items (id, project_id, project_sequence, worktree) VALUES "
                "(101, 2, 101, 'YOK-101'), (102, 2, 102, NULL)"
            )
            register_machine_checkout(tmp_path / "machine-config", tmp_path / "buzz", 2)
            conn.commit()
            yield conn
        finally:
            conn.close()


class TestWebappValidationRecipe:
    def test_creates_empty_validation_surface(self, tmp_path: Path) -> None:
        target = tmp_path / "buzz-validation.db"
        dispatch_recipe(RECIPE_WEBAPP_SQLITE_EMPTY, target, {})

        # Generic SQLite validation DB: this is a webapp validation file, not
        # the Yoke control plane, so opening it with sqlite3 is intentional.
        conn = sqlite3.connect(str(target))
        try:
            tables = _get_tables(conn)
        finally:
            conn.close()

        assert tables == ["schema_version"]

    def test_unknown_recipe_raises_with_context(self, tmp_path: Path) -> None:
        with pytest.raises(UnknownValidationRecipe) as excinfo:
            dispatch_recipe(
                "missing_recipe",
                tmp_path / "validation.db",
                {},
                project="buzz",
                model="primary",
            )
        msg = str(excinfo.value)
        assert "missing_recipe" in msg
        assert "buzz" in msg
        assert "primary" in msg


class TestProjectConfiguredPythonRunner:
    def test_dispatches_python_module_from_project_configured_dir(
        self, tmp_path: Path
    ) -> None:
        module_path = _write_python_migration(
            tmp_path,
            "001_add_accounts",
            "from yoke_core.domain.schema_common import _table_exists\n"
            "\n"
            "def apply(conn):\n"
            "    conn.execute('CREATE TABLE accounts (id INTEGER PRIMARY KEY)')\n"
            "\n"
            "def invariants(conn):\n"
            "    assert _table_exists(conn, 'accounts')\n",
        )

        handle = dispatch_handle(
            model=_webapp_python_model(),
            repo_path=tmp_path,
            identifier="001_add_accounts",
            project="buzz",
            model_name="primary",
        )

        assert handle.kind == RUNNER_KIND_GOVERNED_MODULE
        assert handle.identifier == "001_add_accounts"
        assert handle.source_path == module_path

        # Generic SQLite validation DB: Buzz/webapp migration modules rehearse
        # against sqlite_file/worktree_local_sqlite surfaces outside Yoke
        # authority, so this in-memory app DB intentionally stays sqlite3.
        conn = sqlite3.connect(":memory:")
        try:
            handle.apply(conn)
            conn.commit()
            assert _table_exists(conn, "accounts")
            assert handle.invariants is not None
            handle.invariants(conn)
        finally:
            conn.close()

    def test_missing_python_module_raises(self, tmp_path: Path) -> None:
        (tmp_path / "app" / "db" / "migrations").mkdir(parents=True)
        with pytest.raises(ModuleResolutionError, match="missing_module"):
            dispatch_handle(
                model=_webapp_python_model(),
                repo_path=tmp_path,
                identifier="missing_module",
            )

    def test_unknown_runner_kind_raises_with_context(self, tmp_path: Path) -> None:
        model = _webapp_python_model()
        model["runner"]["kind"] = "bogus_runner"
        with pytest.raises(UnknownRunnerKind) as excinfo:
            dispatch_handle(
                model=model,
                repo_path=tmp_path,
                identifier="001_add_accounts",
                project="buzz",
                model_name="primary",
            )
        msg = str(excinfo.value)
        assert "bogus_runner" in msg
        assert "buzz" in msg
        assert "primary" in msg

    def test_known_runner_kinds_lists_python_runner_only(self) -> None:
        assert known_runner_kinds() == frozenset({RUNNER_KIND_GOVERNED_MODULE})


class TestEnsureMigrationAuditTable:
    """Regression coverage for the YOK-1879 miss: webapp authoritative DBs
    don't get migration_audit from the webapp_sqlite_empty recipe, so
    rehearse/live-apply must bootstrap it before the first audit insert."""

    def test_creates_table_on_empty_db(self, tmp_path: Path) -> None:
        target = tmp_path / "authoritative.db"
        # Generic SQLite authoritative DB: webapp projects can still declare
        # sqlite_file databases, separate from Yoke's Postgres control plane.
        conn = sqlite3.connect(str(target))
        try:
            ensure_migration_audit_table(conn)
            tables = _get_tables(conn)
        finally:
            conn.close()
        assert tables == ["migration_audit"]

    def test_idempotent_when_called_twice(self, tmp_path: Path) -> None:
        target = tmp_path / "authoritative.db"
        # Generic SQLite authoritative DB, deliberately not a Yoke authority
        # probe; table existence delegates through schema_common for portability.
        conn = sqlite3.connect(str(target))
        try:
            ensure_migration_audit_table(conn)
            ensure_migration_audit_table(conn)
            exists = _table_exists(conn, "migration_audit")
        finally:
            conn.close()
        assert exists

    def test_table_accepts_insert_after_bootstrap(self, tmp_path: Path) -> None:
        """The exact failure mode YOK-1882 hit: _insert_audit_row needs
        migration_audit to exist on the authoritative DB. Confirm an
        insert with the canonical required-NOT-NULL columns succeeds
        immediately after ensure_migration_audit_table."""
        target = tmp_path / "authoritative.db"
        # Generic SQLite authoritative DB: verifies sqlite_file project support
        # survives independently of the Yoke control-plane backend.
        conn = sqlite3.connect(str(target))
        try:
            ensure_migration_audit_table(conn)
            conn.execute(
                "INSERT INTO migration_audit "
                "(migration_name, tables_declared, expected_deltas, "
                " pre_row_counts, backup_path, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("006_add_wacky", "[]", "{}", "{}", "", "2026-05-27T20:00:00Z"),
            )
            conn.commit()
            row = conn.execute(
                "SELECT migration_name, state FROM migration_audit"
            ).fetchone()
        finally:
            conn.close()
        assert row == ("006_add_wacky", "planned")


class TestDefaultWorktreePath:
    """Regression coverage for the cwd-default trap.

    A wrong-cwd `migration_apply rehearse YOK-N` used to silently
    provision a Buzz validation surface under Yoke's checkout because
    the wrapper defaulted worktree_path to Path.cwd(). default_worktree_path
    now prefers the item's machine-local project worktree.
    """

    def test_prefers_item_worktree_over_cwd(self, tmp_path: Path) -> None:
        with _seeded_default_worktree_db(tmp_path) as conn:
            resolved = default_worktree_path(conn, 101)
        assert resolved == tmp_path / "buzz" / ".worktrees" / "YOK-101"

    def test_falls_back_to_cwd_when_item_has_no_worktree(
        self, tmp_path: Path
    ) -> None:
        with _seeded_default_worktree_db(tmp_path) as conn:
            resolved = default_worktree_path(conn, 102)
        assert resolved == Path.cwd()

    def test_explicit_override_wins(self, tmp_path: Path) -> None:
        override = Path("/explicit/override/worktree")
        with _seeded_default_worktree_db(tmp_path) as conn:
            resolved = default_worktree_path(conn, 101, override=override)
        assert resolved == override

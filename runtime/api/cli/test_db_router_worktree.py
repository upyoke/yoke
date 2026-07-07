"""Worktree-resolution tests for ``yoke_core.cli.db_router``.

Companion to ``test_db_router.py``. Covers the path-stripping helper
plus end-to-end query dispatch from a linked worktree, including:

- main-checkout DB resolution from a worktree-local ``__file__``
- ignoring a pre-existing stray worktree DB
- explicit ``YOKE_DB`` override winning over derivation
- ``YOKE_ROOT`` shapes and the schema module's parallel resolution
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Tuple

import pytest

from yoke_core.cli import db_router
from yoke_core.domain import db_backend, machine_config, yoke_connected_env


def _reset_init_flag() -> None:
    os.environ.pop("YOKE_DB_INIT_DONE", None)


def _run(argv: list) -> Tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = db_router.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestWorktreeResolution:
    """Ensure db_router from a linked worktree resolves the main-checkout DB."""

    @staticmethod
    def _seed_items_db(db_path: Path, count: int) -> None:
        # Guard-subject sqlite: builds the legacy on-disk DB file these
        # tests prove the Postgres-authority resolver refuses to adopt.
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT)")
            conn.executemany(
                "INSERT INTO items (id, title) VALUES (?, ?)",
                [(idx, f"item-{idx}") for idx in range(1, count + 1)],
            )

    def _build_linked_worktree_layout(
        self, tmp_path: Path, *, stray_count: int | None = None
    ) -> tuple[Path, Path, Path]:
        main_data = tmp_path / "data"
        main_data.mkdir(exist_ok=True)
        main_db = main_data / "yoke.db"
        if not main_db.exists():
            self._seed_items_db(main_db, count=3)
        (tmp_path / "runtime" / "api").mkdir(parents=True, exist_ok=True)
        wt_root = tmp_path / ".worktrees" / "YOK-99"
        wt_yoke = wt_root / "runtime"
        wt_yoke.mkdir(parents=True, exist_ok=True)
        (wt_yoke / "api" / "cli").mkdir(parents=True, exist_ok=True)
        fake_file = wt_yoke / "api" / "cli" / "db_router.py"
        fake_file.touch()
        wt_data = wt_root / "data"
        wt_data.mkdir(exist_ok=True)
        stray_db = wt_data / "yoke.db"
        if stray_count is not None:
            self._seed_items_db(stray_db, count=stray_count)
        return main_db, fake_file, stray_db

    @staticmethod
    def _write_connected_postgres_binding(repo_root: Path, dsn_file: Path) -> None:
        binding = repo_root / ".yoke" / "config.json"
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "active_env": "prod-db-admin",
                    "connections": {
                        "prod-db-admin": {
                            "transport": "local-postgres",
                            "credential_source": {
                                "kind": "dsn_file",
                                "path": str(dsn_file),
                            },
                        },
                    },
                    "projects": {
                        str(repo_root.resolve()): {
                            "project_id": 1,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _clear_authority_env(monkeypatch: pytest.MonkeyPatch) -> None:
        keys = (
            "YOKE_DB", "YOKE_ROOT", "YOKE_DB_INIT_DONE",
            "YOKE_DB_INIT_ALLOW", db_backend.PG_DSN_ENV,
            db_backend.PG_DSN_FILE_ENV,
            yoke_connected_env.DISABLE_ENV,
            yoke_connected_env.PYTEST_ENABLE_ENV,
            machine_config.CONFIG_FILE_ENV,
        )
        for key in keys:
            monkeypatch.delenv(key, raising=False)

    def test_strip_worktree_prefix_basic(self) -> None:
        """_strip_worktree_prefix removes .worktrees/<branch>/ from path."""
        p = Path("/home/user/repo/.worktrees/YOK-9999/runtime/api/cli")
        result = db_router._strip_worktree_prefix(p)
        assert result == Path("/home/user/repo")

    def test_strip_worktree_prefix_noop_when_no_worktree(self) -> None:
        """_strip_worktree_prefix is a no-op for normal paths."""
        p = Path("/home/user/repo/runtime/api/cli")
        result = db_router._strip_worktree_prefix(p)
        assert result == p

    def test_repo_root_strips_worktree_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_repo_root returns main checkout when __file__ is under .worktrees/."""
        # Build a fake worktree layout:
        #   tmp_path/runtime/api/cli/db_router.py  (main checkout)
        #   tmp_path/.worktrees/<branch>/runtime/api/cli/db_router.py  (worktree)
        main_api = tmp_path / "runtime" / "api"
        main_api.mkdir(parents=True)
        (main_api / "cli").mkdir()
        (main_api / "cli" / "db_router.py").touch()

        wt_root = tmp_path / ".worktrees" / "YOK-99"
        wt_api = wt_root / "runtime" / "api"
        wt_api.mkdir(parents=True)
        (wt_api / "cli").mkdir()
        fake_file = wt_api / "cli" / "db_router.py"
        fake_file.touch()

        # Monkey-patch __file__ to the worktree location
        monkeypatch.setattr(db_router, "__file__", str(fake_file))
        result = db_router._repo_root()
        # Must resolve to main checkout, not the worktree
        assert ".worktrees" not in str(result)
        assert result == tmp_path

    def test_connected_postgres_binding_does_not_export_sqlite_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ambient connected-env Postgres must not be pinned back to SQLite."""
        main_db, fake_file, _ = self._build_linked_worktree_layout(tmp_path)
        dsn_file = tmp_path / "target.dsn"
        dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
        self._write_connected_postgres_binding(tmp_path, dsn_file)
        self._clear_authority_env(monkeypatch)
        monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
        monkeypatch.setenv(
            machine_config.CONFIG_FILE_ENV,
            str(tmp_path / ".yoke" / "config.json"),
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(db_router, "__file__", str(fake_file))
        seen: dict[str, object] = {}

        def fake_dispatch(module_name: str, argv: list[str]) -> int:
            seen["module_name"] = module_name
            seen["argv"] = argv
            seen["yoke_db"] = os.environ.get("YOKE_DB")
            return 0

        monkeypatch.setattr(db_router, "_dispatch_python_module", fake_dispatch)

        rc, out, err = _run(["items", "get", "YOK-1", "status"])

        assert rc == 0
        assert out == ""
        assert err == ""
        assert seen["module_name"] == "yoke_core.domain.query_items_cli"
        assert seen["argv"] == ["get", "YOK-1", "status"]
        assert seen["yoke_db"] is None
        assert os.environ.get("YOKE_DB") is None
        assert main_db.exists(), "the old SQLite file may exist but must not win"

    def test_connected_postgres_query_refuses_raw_sqlite_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raw query fallback must not read stale SQLite under connected PG."""
        _, fake_file, _ = self._build_linked_worktree_layout(tmp_path)
        dsn_file = tmp_path / "target.dsn"
        dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
        self._write_connected_postgres_binding(tmp_path, dsn_file)
        self._clear_authority_env(monkeypatch)
        monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
        monkeypatch.setenv(
            machine_config.CONFIG_FILE_ENV,
            str(tmp_path / ".yoke" / "config.json"),
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(db_router, "__file__", str(fake_file))

        rc, out, err = _run(["query", "SELECT COUNT(*) FROM items"])

        assert rc == 1
        assert out == ""
        assert "aurora" in err
        assert os.environ.get("YOKE_DB") is None

    def test_yoke_root_no_stray_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5: repo-root YOKE_ROOT must not create
        ``<repo>/yoke.db`` as a side effect."""
        repo = tmp_path / "testrepo"
        state_dir = repo / "data"
        state_dir.mkdir(parents=True)
        canonical_db = state_dir / "yoke.db"
        self._seed_items_db(canonical_db, count=2)
        _, fake_file, _ = self._build_linked_worktree_layout(tmp_path)

        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setenv("YOKE_ROOT", str(repo))
        monkeypatch.setattr(db_router, "__file__", str(fake_file))

        _run(["query", "SELECT COUNT(*) FROM items"])
        stray = repo / "yoke.db"
        assert not stray.exists(), "repo-root YOKE_ROOT must not create <repo>/yoke.db"

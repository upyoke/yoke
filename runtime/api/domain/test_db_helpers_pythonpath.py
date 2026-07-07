"""Postgres cutover guard for DB path resolution via ``PYTHONPATH``.

Import-root discovery of ``data/yoke.db`` was a SQLite-era convenience. The
Postgres-native cutover requires explicit test fixtures or connected Postgres
authority; merely having a Yoke checkout on ``PYTHONPATH`` must not revive a
retired local DB authority.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_helpers, machine_config, yoke_connected_env


@pytest.fixture
def stub_walk_resolver(monkeypatch):
    """Force the cwd-based walk-up resolver to miss so the new
    ``PYTHONPATH`` heuristic is what's actually exercised.

    ``db_helpers.resolve_db_path`` imports
    :func:`yoke_core.domain.worktree_paths.resolve_db_path` directly
    inside its function body, so the patch must target that lightweight
    module (not the heavy ``worktree`` facade) to take effect.
    """
    from yoke_core.domain import worktree_paths as wt_paths
    monkeypatch.setattr(
        wt_paths, "resolve_db_path", lambda **kw: None, raising=False,
    )


def _write_connected_env(root):
    dsn_file = root / "target.dsn"
    dsn_file.write_text("host=target dbname=yoke\n", encoding="utf-8")
    binding = root / ".yoke" / "config.json"
    binding.parent.mkdir(parents=True, exist_ok=True)
    binding.write_text(
        f"""
{{
  "schema_version": 1,
  "active_env": "prod-db-admin",
  "connections": {{
    "prod-db-admin": {{
      "transport": "local-postgres",
      "credential_source": {{"kind": "dsn_file", "path": "{dsn_file}"}}
    }}
  }},
  "projects": {{
    "{root.resolve()}": {{"project_id": 1, "project": "yoke"}}
  }}
}}
""".strip(),
        encoding="utf-8",
    )


def _clear_db_env(monkeypatch, root):
    monkeypatch.delenv("YOKE_DB", raising=False)
    monkeypatch.delenv("YOKE_ROOT", raising=False)
    monkeypatch.delenv(machine_config.CONFIG_FILE_ENV, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    _write_connected_env(root)
    monkeypatch.setenv(
        machine_config.CONFIG_FILE_ENV,
        str(root / ".yoke" / "config.json"),
    )
    monkeypatch.chdir(root)


def _assert_sqlite_authority_retired() -> None:
    with pytest.raises(RuntimeError, match="SQLite authority retired/guarded"):
        db_helpers.resolve_db_path()


class TestResolveDbPathPythonPath:
    def test_pythonpath_with_yoke_entry_does_not_resolve_db(
        self, tmp_path, monkeypatch, stub_walk_resolver,
    ):
        yoke_root = tmp_path / "yoke-checkout"
        (yoke_root / "data").mkdir(parents=True)
        db_file = yoke_root / "data" / "yoke.db"
        db_file.write_bytes(b"")

        _clear_db_env(monkeypatch, tmp_path)
        monkeypatch.setenv("PYTHONPATH", str(yoke_root))
        monkeypatch.chdir(tmp_path)

        _assert_sqlite_authority_retired()

    def test_foreign_cwd_plus_yoke_pythonpath_does_not_construct_foreign(
        self, tmp_path, monkeypatch, stub_walk_resolver,
    ):
        foreign_cwd = tmp_path / "foreign-project"
        foreign_cwd.mkdir()
        yoke_root = tmp_path / "yoke-checkout"
        (yoke_root / "data").mkdir(parents=True)
        (yoke_root / "data" / "yoke.db").write_bytes(b"")

        _clear_db_env(monkeypatch, tmp_path)
        monkeypatch.setenv("PYTHONPATH", str(yoke_root))
        monkeypatch.chdir(foreign_cwd)

        _assert_sqlite_authority_retired()

    def test_pythonpath_without_db_file_raises(
        self, tmp_path, monkeypatch, stub_walk_resolver,
    ):
        non_yoke = tmp_path / "not-yoke"
        non_yoke.mkdir()

        _clear_db_env(monkeypatch, tmp_path)
        monkeypatch.setenv("PYTHONPATH", str(non_yoke))
        monkeypatch.chdir(tmp_path)

        _assert_sqlite_authority_retired()

    def test_empty_pythonpath_raises_when_resolver_misses(
        self, tmp_path, monkeypatch, stub_walk_resolver,
    ):
        _clear_db_env(monkeypatch, tmp_path)
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.chdir(tmp_path)

        _assert_sqlite_authority_retired()

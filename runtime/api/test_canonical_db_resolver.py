"""Tests for ``runtime.api.fixtures.canonical_db``.

The shared helper is retained as a guard around the retired root
``data/yoke.db`` path. It must not ambiently export ``YOKE_DB`` for
Postgres-native runs, while explicit isolated fixture DB values still pass
through for legacy unit tests.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain import machine_config


CANONICAL_DB_MODULE = "runtime.api.fixtures.canonical_db"


def _import_helper(monkeypatch):
    """Re-import the helper with a clean ``YOKE_DB`` snapshot.

    The conftest already imported the helper at session start, but each test
    needs the module-level functions, not the import-time side effect, so a
    clean import is unnecessary — we just import the module.
    """
    import importlib
    import runtime.api.fixtures.canonical_db as mod

    return importlib.reload(mod)


class TestResolveCanonicalYokeDb:
    def test_returns_none_for_retired_root_db_in_repo(self, monkeypatch):
        helper = _import_helper(monkeypatch)
        path = helper.resolve_canonical_yoke_db()
        assert path is None

    def test_returns_none_when_resolver_raises(self, monkeypatch):
        helper = _import_helper(monkeypatch)

        def _boom(_mode):
            raise RuntimeError("resolver intentionally failed")

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_named_path", _boom
        )
        # Re-import so the helper picks up the patched attribute through its
        # imported reference.
        import importlib
        import runtime.api.fixtures.canonical_db as mod

        mod = importlib.reload(mod)
        assert mod.resolve_canonical_yoke_db() is None


class TestExportCanonicalYokeDb:
    def test_does_not_overwrite_existing_value(self, monkeypatch, tmp_path):
        sentinel = str(tmp_path / "fixture.db")
        monkeypatch.setenv("YOKE_DB", sentinel)
        helper = _import_helper(monkeypatch)
        result = helper.export_canonical_yoke_db()
        assert result == sentinel, (
            "explicit YOKE_DB must win; the resolver should not stomp it"
        )
        assert os.environ["YOKE_DB"] == sentinel

    def test_existing_fixture_db_does_not_change_postgres_authority(
        self, monkeypatch, tmp_path
    ):
        repo = tmp_path / "repo"
        binding = repo / ".yoke" / "config.json"
        binding.parent.mkdir(parents=True)
        dsn_file = tmp_path / "target.dsn"
        dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
        binding.write_text(
            json.dumps({
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "authority": {
                            "kind": "aws_aurora_postgres",
                            "infra_dir": "projects/yoke/infra",
                            "location": {
                                "stack": "yoke-prod",
                                "database_name": "yoke_prod",
                            },
                        },
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn_file),
                        },
                    },
                },
                "projects": {
                    str(repo.resolve()): {"project_id": 1, "project": "yoke"}
                },
            }),
            encoding="utf-8",
        )
        monkeypatch.chdir(repo)
        monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
        sentinel = str(tmp_path / "fixture.db")
        monkeypatch.setenv("YOKE_DB", sentinel)
        helper = _import_helper(monkeypatch)

        assert helper.export_canonical_yoke_db() == sentinel
        from yoke_core.domain import db_backend

        assert db_backend.is_postgres()

    def test_does_not_set_when_unset_even_if_resolvable(self, monkeypatch, tmp_path):
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setenv("YOKE_CONNECTED_ENV_DISABLE", "1")
        helper = _import_helper(monkeypatch)
        resolved = str(tmp_path / "repo" / "data" / "yoke.db")
        monkeypatch.setattr(helper, "resolve_canonical_yoke_db", lambda: resolved)
        result = helper.export_canonical_yoke_db()
        assert result is None
        assert "YOKE_DB" not in os.environ

    def test_returns_none_when_connected_postgres_retires_sqlite(
        self, monkeypatch, tmp_path
    ):
        repo = tmp_path / "repo"
        binding = repo / ".yoke" / "config.json"
        binding.parent.mkdir(parents=True, exist_ok=True)
        dsn_file = tmp_path / "target.dsn"
        dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
        binding.write_text(
            json.dumps({
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
                    str(repo.resolve()): {"project_id": 1, "project": "yoke"}
                },
            }),
            encoding="utf-8",
        )
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
        helper = _import_helper(monkeypatch)
        monkeypatch.setattr(
            helper,
            "resolve_canonical_yoke_db",
            lambda: str(repo / "data" / "yoke.db"),
        )

        result = helper.export_canonical_yoke_db()

        assert result is None
        assert "YOKE_DB" not in os.environ

    def test_returns_none_when_unset_and_unresolvable(self, monkeypatch):
        monkeypatch.delenv("YOKE_DB", raising=False)

        def _boom(_mode):
            raise RuntimeError("resolver intentionally failed")

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_named_path", _boom
        )
        import importlib
        import runtime.api.fixtures.canonical_db as mod

        mod = importlib.reload(mod)
        result = mod.export_canonical_yoke_db()
        assert result is None
        assert "YOKE_DB" not in os.environ


class TestAssertCanonicalYokeDb:
    def test_raises_without_explicit_fixture_db(self, monkeypatch, tmp_path):
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setenv("YOKE_CONNECTED_ENV_DISABLE", "1")
        helper = _import_helper(monkeypatch)
        resolved = str(tmp_path / "repo" / "data" / "yoke.db")
        monkeypatch.setattr(helper, "resolve_canonical_yoke_db", lambda: resolved)
        with pytest.raises(helper.CanonicalDbResolutionError) as excinfo:
            helper.assert_canonical_yoke_db()
        msg = str(excinfo.value)
        assert "YOKE_PG_DSN" in msg
        assert "isolated fixture DB" in msg

    def test_returns_explicit_fixture_db(self, monkeypatch, tmp_path):
        fixture_db = str(tmp_path / "fixture.db")
        monkeypatch.setenv("YOKE_DB", fixture_db)
        helper = _import_helper(monkeypatch)
        assert helper.assert_canonical_yoke_db() == fixture_db

    def test_raises_when_resolver_fails(self, monkeypatch):
        monkeypatch.delenv("YOKE_DB", raising=False)

        def _boom(_mode):
            raise RuntimeError("resolver intentionally failed")

        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_named_path", _boom
        )
        import importlib
        import runtime.api.fixtures.canonical_db as mod

        mod = importlib.reload(mod)
        with pytest.raises(mod.CanonicalDbResolutionError) as excinfo:
            mod.assert_canonical_yoke_db()
        # The error must name the resolver and the recovery path so the
        # operator can act on it without further hunting.
        msg = str(excinfo.value)
        assert "yoke_core.domain.worktree paths db" in msg
        assert "YOKE_PG_DSN" in msg


class TestHarnessUniversalConsumption:
    """A harness-shared contract is only honest if multiple harnesses can
    consume it. We assert by structure, not by enumerating every harness:
    the helper module ships under ``runtime/api/fixtures/`` (Yoke core),
    not under any ``runtime/harness/{harness}/`` adapter, so every harness
    that runs ``python3 -m pytest runtime/api/`` automatically picks it up
    via the shared conftest.

    These checks fail loudly if a future refactor pushes the resolver
    into a harness-specific location or hides it behind a shell wrapper.
    """

    def test_helper_lives_under_runtime_api_fixtures(self):
        import runtime.api.fixtures.canonical_db as mod

        assert Path(mod.__file__).parent.name == "fixtures", (
            "canonical_db helper must live under runtime/api/fixtures/ so "
            "every harness consumes it through the shared conftest"
        )
        assert Path(mod.__file__).parents[1].name == "api"
        assert Path(mod.__file__).parents[2].name == "runtime"

    def test_no_dot_sh_companion(self):
        """Helper must be Python-owned. No ``.sh`` companion may
        exist alongside the resolver."""
        helper_dir = (
            Path(__file__).resolve().parent / "fixtures"
        )
        sh_files = list(helper_dir.glob("canonical_db*.sh"))
        assert sh_files == [], (
            "canonical_db helper must remain Python-owned; no shell "
            f"companion permitted, found {sh_files}"
        )

    def test_conftest_no_longer_imports_the_helper(self):
        conftest = (
            Path(__file__).resolve().parent / "conftest.py"
        ).read_text(encoding="utf-8")
        assert "from runtime.api.fixtures.canonical_db import" not in conftest
        assert "export_canonical_yoke_db()" not in conftest

    def test_cli_surface_refuses_retired_root_db_path(self):
        """The CLI surface mirrors the operator-facing retired-path guard."""
        result = subprocess.run(
            [sys.executable, "-m", CANONICAL_DB_MODULE],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "YOKE_DB": "",
                "YOKE_CONNECTED_ENV_DISABLE": "1",
            },
        )
        assert result.returncode == 1
        assert "root Yoke DB file authority is retired" in result.stderr

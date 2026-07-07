"""Tests for the ``command_definitions`` read API and CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Iterator, List

import pytest

from yoke_core.domain import command_definitions as cmd_defs
from yoke_core.domain import db_backend
from yoke_core.domain import project_structure as ps
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


NOW = "2026-04-20T00:00:00Z"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_project(db: str, slug: str, project_id: int) -> None:
    conn = connect_test_db(db)
    try:
        p = _p(conn)
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (project_id, slug, slug, NOW),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Iterator[str]:
    # Backend-aware per-test DB: a real file on SQLite, a disposable per-test
    # database on Postgres (YOKE_PG_DSN repointed for the context). Isolation
    # is the load-bearing property here — without it the Postgres tests share
    # the DSN-pointed database and one test's seeds pollute the next.
    with init_test_db(tmp_path, apply_schema=lambda: ps.cmd_init()) as path:
        _seed_project(path, "buzz", SEED_PROJECT_IDS["buzz"])
        yield path


def _seed(db: str, project: str, scope: str, command: str) -> None:
    ps.apply_patch(
        project,
        ops=[{
            "op": "put",
            "family": "command_definitions",
            "attachment": "project",
            "entry_key": scope,
            "payload": {"command": command},
        }],
        db_path=db,
    )


class TestReadAPI:
    def test_get_returns_none_when_absent(self, db_path: str):
        assert cmd_defs.get_command("buzz", "quick", db_path=db_path) is None

    def test_get_returns_command_string(self, db_path: str):
        _seed(db_path, "buzz", "quick", "pytest tests/")
        assert cmd_defs.get_command("buzz", "quick", db_path=db_path) == "pytest tests/"

    def test_get_returns_none_for_empty_command(self, db_path: str):
        _seed(db_path, "buzz", "quick", "")
        assert cmd_defs.get_command("buzz", "quick", db_path=db_path) is None

    def test_get_rejects_unknown_scope(self, db_path: str):
        with pytest.raises(ValueError, match="Unknown command_definitions scope"):
            cmd_defs.get_command("buzz", "integration", db_path=db_path)

    def test_list_returns_canonical_scope_order(self, db_path: str):
        _seed(db_path, "buzz", "smoke", "smoke-cmd")
        _seed(db_path, "buzz", "quick", "quick-cmd")
        _seed(db_path, "buzz", "full", "full-cmd")
        out = cmd_defs.list_commands("buzz", db_path=db_path)
        assert list(out.keys()) == ["quick", "full", "smoke"]

    def test_list_skips_empty_commands(self, db_path: str):
        _seed(db_path, "buzz", "quick", "qc")
        _seed(db_path, "buzz", "full", "")
        out = cmd_defs.list_commands("buzz", db_path=db_path)
        assert out == {"quick": "qc"}


class TestCli:
    def _run(self, argv: List[str], monkeypatch, db_path: str):
        monkeypatch.setenv("YOKE_DB", db_path)
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_defs.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_get_prints_command(self, db_path: str, monkeypatch):
        _seed(db_path, "buzz", "quick", "pytest tests/")
        rc, out, _ = self._run(["get", "buzz", "quick"], monkeypatch, db_path)
        assert rc == 0
        assert out.strip() == "pytest tests/"

    def test_get_empty_when_absent(self, db_path: str, monkeypatch):
        rc, out, _ = self._run(["get", "buzz", "quick"], monkeypatch, db_path)
        assert rc == 0
        assert out == ""

    def test_get_unknown_scope_exits_2(self, db_path: str, monkeypatch):
        rc, _, err = self._run(["get", "buzz", "integration"], monkeypatch, db_path)
        assert rc == 2
        assert "Unknown command_definitions scope" in err

    def test_list_prints_scope_equals_command(self, db_path: str, monkeypatch):
        _seed(db_path, "buzz", "quick", "qc")
        _seed(db_path, "buzz", "full", "fc")
        rc, out, _ = self._run(["list", "buzz"], monkeypatch, db_path)
        assert rc == 0
        assert out.splitlines() == ["quick=qc", "full=fc"]

    def test_scopes_prints_vocabulary(self, db_path: str, monkeypatch):
        rc, out, _ = self._run(["scopes"], monkeypatch, db_path)
        assert rc == 0
        assert out.splitlines() == list(cmd_defs.SCOPES)

    def test_no_subcmd_exits_2(self, db_path: str, monkeypatch):
        rc, _, err = self._run([], monkeypatch, db_path)
        assert rc == 2
        assert "Usage" in err

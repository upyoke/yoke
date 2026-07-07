from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from yoke_core.cli import db_router_init
from yoke_core.api import service_client_shared_io
from yoke_core.domain import (
    backlog_queries,
    backlog_github_fetch,
    db_backend,
    db_helpers,
    db_mutation_gate_implementing,
    machine_config,
    merge_lock,
    qa_gates,
    yoke_connected_env,
)
from yoke_core.engines import _merge_worktree_runtime, done_transition_runtime


def _connected_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    binding = repo / ".yoke" / "config.json"
    binding.parent.mkdir(parents=True)
    dsn_file = tmp_path / "aurora.dsn"
    dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
    binding.write_text(
        json.dumps(
            {
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
                    str(repo.resolve()): {
                        "project_id": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    return repo


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "YOKE_DB",
        "YOKE_ROOT",
        db_backend.PG_DSN_ENV,
        db_backend.PG_DSN_FILE_ENV,
        yoke_connected_env.DISABLE_ENV,
        yoke_connected_env.PYTEST_ENABLE_ENV,
        machine_config.CONFIG_FILE_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")


def test_connected_env_selects_postgres_without_touching_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    assert db_backend.is_postgres()
    assert db_backend.resolve_pg_dsn() == "host=aurora dbname=yoke_prod"
    with pytest.raises(RuntimeError, match="SQLite authority retired/guarded"):
        db_helpers.resolve_db_path()
    assert not (repo / "data" / "yoke.db").exists()


def test_db_router_probe_skips_sqlite_in_connected_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    assert db_router_init._probe_schema_or_remediate(["items", "list"]) is None
    assert not (repo / "data" / "yoke.db").exists()


def test_explicit_fixture_db_does_not_change_postgres_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    fixture_db = tmp_path / "fixture.db"
    # Guard-subject sqlite: a real legacy DB file the Postgres authority
    # must ignore even when YOKE_DB points at it.
    sqlite3.connect(fixture_db).close()
    monkeypatch.chdir(repo)
    monkeypatch.setenv("YOKE_DB", str(fixture_db))

    assert db_backend.is_postgres()
    assert db_backend.resolve_pg_dsn() == "host=aurora dbname=yoke_prod"


def test_backlog_write_resolver_does_not_request_sqlite_path_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    assert db_backend.is_postgres()
    assert backlog_queries._resolve_write_db_path() == ""
    backlog_queries._assert_write_db_ready("")
    assert not (repo / "data" / "yoke.db").exists()


def test_github_sync_opener_uses_backend_factory_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    sentinel = object()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(db_backend, "connect", lambda path=None: sentinel)
    monkeypatch.setattr(
        "yoke_core.domain.epic_task_sync._db_path",
        lambda: pytest.fail("should not resolve a SQLite DB path"),
    )

    conn, owns = backlog_github_fetch._open_conn(None)

    assert conn is sentinel
    assert owns is True
    assert not (repo / "data" / "yoke.db").exists()


def test_github_sync_item_fields_casts_values_before_coalescing() -> None:
    class FakeCursor:
        def fetchone(self) -> tuple[int]:
            return (1,)

    class FakeConn:
        sql = ""
        params: tuple[str, ...] = ()

        def execute(self, sql: str, params: tuple[str, ...]) -> FakeCursor:
            self.sql = sql
            self.params = params
            return FakeCursor()

    conn = FakeConn()

    assert backlog_github_fetch._item_fields("1897", ["blocked"], conn=conn) == {
        "blocked": "1"
    }
    assert "COALESCE(CAST(i.blocked AS TEXT), '')" in conn.sql
    assert conn.params == ("1897",)


def test_migration_evidence_gate_resolves_connected_postgres_audit_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        db_helpers,
        "resolve_db_path",
        lambda: pytest.fail("should not resolve a SQLite DB path"),
    )

    audit_target = db_mutation_gate_implementing._resolve_audit_db_path(
        repo,
        {"authoritative_db": {"kind": "aws_aurora_postgres"}},
    )

    assert audit_target == db_mutation_gate_implementing.CONNECTED_POSTGRES_AUDIT_TOKEN
    assert not (repo / "data" / "yoke.db").exists()


def test_qa_gate_cli_resolver_does_not_request_sqlite_path_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        db_helpers,
        "resolve_db_path",
        lambda: pytest.fail("should not resolve a SQLite DB path"),
    )

    assert qa_gates._resolve_cli_db_path(None) == ""
    assert not (repo / "data" / "yoke.db").exists()


def test_service_client_child_env_forwards_connected_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    assert service_client_shared_io._subprocess_backend_env() == {
        machine_config.CONFIG_FILE_ENV: str(
            repo / ".yoke" / "config.json"
        ),
        db_backend.PG_DSN_FILE_ENV: str(tmp_path / "aurora.dsn"),
    }


def test_merge_engine_runtime_uses_backend_connection_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    sentinel = object()
    monkeypatch.setattr(db_backend, "connect", lambda *args, **kwargs: sentinel)

    assert _merge_worktree_runtime._db_path() == ""
    assert _merge_worktree_runtime._connect() is sentinel
    assert not (repo / "data" / "yoke.db").exists()


def test_merge_engine_child_env_does_not_force_sqlite_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_merge_worktree_runtime.subprocess, "run", fake_run)

    _merge_worktree_runtime._run_python_module(
        "yoke_core.domain.schema", ["init"], capture=True
    )

    env = captured["env"]
    assert isinstance(env, dict)
    assert "YOKE_DB" not in env
    assert not (repo / "data" / "yoke.db").exists()


def test_done_transition_runtime_uses_backend_connection_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    sentinel = object()
    monkeypatch.setattr(db_backend, "connect", lambda *args, **kwargs: sentinel)

    assert done_transition_runtime._db_path() == ""
    assert done_transition_runtime._connect() is sentinel
    assert not (repo / "data" / "yoke.db").exists()


def test_merge_lock_uses_backend_connection_in_postgres_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear(monkeypatch)
    repo = _connected_repo(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    sentinel = object()
    monkeypatch.setattr(db_backend, "connect", lambda *args, **kwargs: sentinel)

    assert merge_lock._db_path() == ""
    assert merge_lock._connect() is sentinel
    assert not (repo / "data" / "yoke.db").exists()

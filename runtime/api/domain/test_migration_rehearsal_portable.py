"""Native rehearsal orchestration for SQLite and declared external validation.

The control plane and external connection are seams; the SQLite migration runs
against a real file. Live PostgreSQL rehearsal remains in test_migration_apply.
"""

from contextlib import nullcontext
import json
import sqlite3
from types import SimpleNamespace

import pytest

from yoke_core.domain import migration_apply_rehearse as rehearsal
from yoke_core.domain import migration_apply_targets as targets
from yoke_core.domain.migration_apply_contract import STATE_REHEARSED
from yoke_core.domain.migration_apply_runners import RUNNER_KIND_GOVERNED_MODULE


def test_rehearsal_applies_sqlite_only_to_worktree_validation(tmp_path, monkeypatch):
    modules = tmp_path / "migrations"
    modules.mkdir()
    (modules / "001_widgets.py").write_text(
        "def apply(conn):\n conn.execute('CREATE TABLE widgets (id INTEGER PRIMARY KEY)')\n"
        "def invariants(conn):\n assert conn.execute('SELECT count(*) FROM widgets').fetchone()[0] == 0\n",
        encoding="utf-8",
    )
    authority = targets.DbTarget(
        "sqlite_file", str(tmp_path / "authority.db"), "authority"
    )
    validation = targets.DbTarget(
        "sqlite_file", str(tmp_path / "validation.db"), "validation"
    )
    sqlite3.connect(authority.target).close()
    model = {
        "authoritative_db": {"kind": "sqlite_file"},
        "validation_surface": {"kind": "worktree_local_sqlite"},
        "runner": {
            "kind": RUNNER_KIND_GOVERNED_MODULE,
            "config": {
                "modules_dir": "migrations",
                "connection_env_var": "APP_DB_PATH",
            },
        },
    }
    profile = {
        "model_name": "primary",
        "migration_modules": ["001_widgets"],
        "affected_surfaces": [],
    }
    resolved = SimpleNamespace(
        profile=profile, project="sample", project_id=2, attestation_raw=json.dumps({})
    )
    monkeypatch.setattr(rehearsal, "resolve_runner_input", lambda *a, **k: resolved)
    monkeypatch.setattr(
        rehearsal,
        "resolve_rehearsal_targets",
        lambda *a: (model, authority, validation, "APP_DB_PATH"),
    )
    monkeypatch.setattr(
        rehearsal.migration_territory_claim,
        "enter",
        lambda *a, **k: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(rehearsal, "named_restore_point", lambda *a: nullcontext())
    monkeypatch.setattr(
        rehearsal, "fingerprint_db_target", lambda target: "authority-fingerprint"
    )
    receipts = []
    monkeypatch.setattr(
        rehearsal,
        "receipt_writers",
        lambda control: (
            lambda **kw: 1,
            lambda audit_id, state, **kw: receipts.append((audit_id, state)),
        ),
    )
    result = rehearsal._rehearse_inner(
        object(), item_id=101, session_id="fixture", worktree_path=tmp_path
    )
    assert result.all_succeeded
    assert receipts[-1] == (1, STATE_REHEARSED)
    with sqlite3.connect(validation.target) as conn:
        assert conn.execute("SELECT count(*) FROM widgets").fetchone()[0] == 0
    with sqlite3.connect(authority.target) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='widgets'"
        ).fetchall()


def test_external_validation_binds_disposable_postgres_and_rejects_authority(
    monkeypatch, tmp_path
):
    authority = targets.DbTarget("postgres", "dbname=authority", "postgres:authority")
    model = {
        "validation_surface": {"kind": "external_validation"},
        "runner": {"config": {"connection_env_var": "APP_DATABASE_URL"}},
    }
    monkeypatch.setattr(targets, "read_binding", lambda name: "dbname=validation")
    target = targets.resolve_validation_db_target(
        worktree_path=tmp_path,
        project="sample",
        model_name="primary",
        model=model,
        authoritative_target=authority,
        control_db_path=None,
    )
    assert target.kind == "postgres" and target.target == "dbname=validation"
    bound = []
    connection = object()
    monkeypatch.setattr(
        targets.db_backend,
        "bound_pg_dsn",
        lambda dsn: bound.append(dsn) or nullcontext(),
    )
    monkeypatch.setattr(targets.db_backend, "connect", lambda: connection)
    assert targets.connect_db_target(target) is connection
    assert bound == ["dbname=validation"]
    monkeypatch.setattr(targets, "read_binding", lambda name: authority.target)
    with pytest.raises(targets.MigrationApplyError, match="separate validation-only"):
        targets.resolve_validation_db_target(
            worktree_path=tmp_path,
            project="sample",
            model_name="primary",
            model=model,
            authoritative_target=authority,
            control_db_path=None,
        )

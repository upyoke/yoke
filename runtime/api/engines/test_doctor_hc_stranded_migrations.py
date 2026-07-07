"""Tests for HC-stranded-migration-module."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from yoke_core.engines.doctor_hc_stranded_migrations import (
    hc_stranded_migration_module,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


_SCHEMA = """
CREATE TABLE migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL
);
"""


_GOVERNED_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT NOT NULL,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
    created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
);
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    settings TEXT NOT NULL,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
);
"""


def _make_control_conn(*, with_audit_schema: bool = True):
    """Disposable Postgres control-plane DB; dropped on close or GC."""
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    if with_audit_schema:
        apply_fixture_ddl(c, _SCHEMA)
    return c


@pytest.fixture
def conn():
    c = _make_control_conn()
    yield c
    c.close()


def _build_repo(
    tmp_path: Path, *, present_modules,
):
    """Create a fake repo root with the given migration modules present."""
    root = tmp_path / "repo"
    (root / "runtime" / "api" / "domain" / "migrations").mkdir(parents=True)
    (root / "runtime" / "api" / "domain" / "migrations" / "__init__.py").write_text("")
    for name in present_modules:
        (root / "runtime" / "api" / "domain" / "migrations" / f"{name}.py").write_text(
            f"# stub for {name}\n"
        )
    return root


def _run_hc(conn, *, repo_root: Path, monkeypatch) -> RecordCollector:
    rec = RecordCollector()
    args = DoctorArgs()
    import yoke_core.engines.doctor_report as _base
    monkeypatch.setattr(_base, "_resolve_repo_root", lambda: str(repo_root))
    hc_stranded_migration_module(conn, args, rec)
    return rec


def test_pass_when_no_modules_present(conn, tmp_path, monkeypatch):
    root = _build_repo(tmp_path, present_modules=[])
    rec = _run_hc(conn, repo_root=root, monkeypatch=monkeypatch)
    assert rec.results[0].result == "PASS"


def test_pass_when_module_present_but_not_completed(conn, tmp_path, monkeypatch):
    root = _build_repo(tmp_path, present_modules=["pending_module"])
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('pending_module', 'rehearsed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()
    rec = _run_hc(conn, repo_root=root, monkeypatch=monkeypatch)
    assert rec.results[0].result == "PASS"


def test_pass_closed_when_completed_module_has_no_governed_project(
    conn, tmp_path, monkeypatch,
):
    root = _build_repo(tmp_path, present_modules=["stranded_module"])
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('stranded_module', 'completed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()
    rec = _run_hc(conn, repo_root=root, monkeypatch=monkeypatch)
    assert rec.results[0].result == "PASS"
    assert "stranded_module" not in rec.results[0].detail


def test_pass_when_audit_table_missing(tmp_path, monkeypatch):
    c = _make_control_conn(with_audit_schema=False)
    root = _build_repo(tmp_path, present_modules=["any"])
    rec = _run_hc(c, repo_root=root, monkeypatch=monkeypatch)
    c.close()
    assert rec.results[0].result == "PASS"


def _build_buzz_shape_repo(tmp_path: Path):
    """Layout matching Buzz: modules at app/db/migrations/, external
    SQLite DB at app/data/app.db."""
    root = tmp_path / "buzz_repo"
    migrations = root / "app" / "db" / "migrations"
    data_dir = root / "app" / "data"
    migrations.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (migrations / "__init__.py").write_text("")
    return root, migrations, data_dir / "app.db"


def _seed_governed_buzz(
    conn, *, repo_path: Path, modules_dir_rel: str = "app/db/migrations",
    audit_db_rel: str = "app/data/app.db",
):
    """Seed projects + project_capabilities so the project-aware HC
    path discovers a Buzz-shape governed project."""
    apply_fixture_ddl(conn, _GOVERNED_SCHEMA)
    register_machine_checkout(repo_path.parent, repo_path, 2)
    conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
        (2, "buzz", "Buzz"),
    )
    settings = {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "sqlite_file",
                    "location": {"path": audit_db_rel},
                },
                "runner": {
                    "config": {"modules_dir": modules_dir_rel},
                    "kind": "governed_migration_module",
                },
            }
        },
    }
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, 'migration_model', %s)",
        (2, json.dumps(settings)),
    )
    conn.commit()


def _seed_governed_yoke(
    conn, *, repo_path: Path,
    modules_dir_rel: str = "runtime/api/domain/migrations",
):
    """Seed Yoke's Postgres target shape for the project-aware HC path."""
    apply_fixture_ddl(conn, _GOVERNED_SCHEMA)
    register_machine_checkout(repo_path.parent, repo_path, 1)
    conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
        (1, "yoke", "Yoke"),
    )
    settings = {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "postgres",
                    "location": {"database_name": "yoke_prod"},
                },
                "runner": {
                    "config": {"modules_dir": modules_dir_rel},
                    "kind": "governed_migration_module",
                },
            }
        },
    }
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, 'migration_model', %s)",
        (1, json.dumps(settings)),
    )
    conn.commit()


def _audit_db_with(audit_db_path: Path, *, name: str, state: str):
    """Create a minimal migration_audit row in a standalone SQLite file.

    Intentional sqlite fixture: the subject is the managed-project
    ``sqlite_file`` authoritative-DB branch the HC probes on disk.
    """
    audit = sqlite3.connect(str(audit_db_path))
    audit.executescript(_SCHEMA)
    audit.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES (?, ?, '2026-04-30T00:00:00Z')",
        (name, state),
    )
    audit.commit()
    audit.close()


def test_warn_when_buzz_shape_project_strands_completed_module(
    conn, tmp_path, monkeypatch,
):
    """Project-aware path: discover Buzz's migration_model, scan its
    modules_dir at app/db/migrations/, read its external
    migration_audit at app/data/app.db, and warn on stranded modules.

    Pre-fix the HC hardcoded runtime/api/domain/migrations on the
    current repo_root and never saw Buzz at all.
    """
    repo, migrations, audit_db = _build_buzz_shape_repo(tmp_path)
    (migrations / "006_add_wacky.py").write_text("def apply(c): pass\n")
    _audit_db_with(audit_db, name="006_add_wacky", state="completed")
    _seed_governed_buzz(conn, repo_path=repo)

    rec = RecordCollector()
    args = DoctorArgs()
    # Repo root resolution does not matter for the project-aware path:
    # checkout location comes from machine config.
    hc_stranded_migration_module(conn, args, rec)
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "buzz:" in detail
    assert "006_add_wacky" in detail
    assert "app/db/migrations" in detail


def test_warn_when_yoke_postgres_project_strands_completed_module(
    conn, tmp_path, monkeypatch,
):
    """Yoke's project-aware Postgres authority reads the connected DB."""
    root = _build_repo(tmp_path, present_modules=["pg_stranded"])
    _seed_governed_yoke(conn, repo_path=root)
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('pg_stranded', 'completed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()

    rec = RecordCollector()
    args = DoctorArgs()
    hc_stranded_migration_module(conn, args, rec)
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "yoke:" in detail
    assert "pg_stranded" in detail
    assert "runtime/api/domain/migrations" in detail


def test_governed_findings_include_sqlite_and_postgres_projects(
    conn, tmp_path, monkeypatch,
):
    """A SQLite-file project finding must not mask Yoke's Postgres finding."""
    buzz_repo, buzz_migrations, buzz_db = _build_buzz_shape_repo(tmp_path)
    (buzz_migrations / "buzz_stranded.py").write_text("def apply(c): pass\n")
    _audit_db_with(buzz_db, name="buzz_stranded", state="completed")
    _seed_governed_buzz(conn, repo_path=buzz_repo)

    yoke_root = _build_repo(tmp_path, present_modules=["yoke_stranded"])
    _seed_governed_yoke(conn, repo_path=yoke_root)
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('yoke_stranded', 'completed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()

    rec = RecordCollector()
    args = DoctorArgs()
    hc_stranded_migration_module(conn, args, rec)
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "buzz:" in detail
    assert "buzz_stranded" in detail
    assert "yoke:" in detail
    assert "yoke_stranded" in detail


def test_project_aware_path_does_not_double_count_legacy_yoke(
    conn, tmp_path, monkeypatch,
):
    """When the conn already declares a governed project, the retired
    Yoke-only scan does not fire."""
    repo, migrations, audit_db = _build_buzz_shape_repo(tmp_path)
    # Buzz has a present module but no completed audit row — clean.
    (migrations / "in_flight.py").write_text("def apply(c): pass\n")
    _audit_db_with(audit_db, name="in_flight", state="rehearsed")
    _seed_governed_buzz(conn, repo_path=repo)

    # Plant a Yoke-shape stranded module in a separate repo_root that
    # the retired fallback would have flagged.
    yoke_root = _build_repo(tmp_path, present_modules=["legacy_stranded"])
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('legacy_stranded', 'completed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()

    rec = _run_hc(conn, repo_root=yoke_root, monkeypatch=monkeypatch)
    assert rec.results[0].result == "PASS"
    assert "legacy_stranded" not in rec.results[0].detail


def test_governed_project_with_missing_audit_db_is_silent(
    conn, tmp_path, monkeypatch,
):
    """An external SQLite DB path that doesn't exist on disk yields no
    findings (no crash, no false positive). Common during project
    bootstrap before the first live-apply."""
    repo, migrations, audit_db = _build_buzz_shape_repo(tmp_path)
    (migrations / "006_add_wacky.py").write_text("def apply(c): pass\n")
    # Deliberately do NOT create audit_db.
    assert not audit_db.exists()
    _seed_governed_buzz(conn, repo_path=repo)

    rec = RecordCollector()
    args = DoctorArgs()
    hc_stranded_migration_module(conn, args, rec)
    assert rec.results[0].result == "PASS"

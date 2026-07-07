"""Boundary tests for stranded migration SQLite exclusions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.engines.doctor_hc_stranded_migrations import (
    hc_stranded_migration_module,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.engines.test_doctor_hc_stranded_migrations import (
    _audit_db_with,
    _build_buzz_shape_repo,
    _build_repo,
    _make_control_conn,
    _seed_governed_buzz,
    _seed_governed_yoke,
)


@pytest.fixture
def conn():
    c = _make_control_conn()
    yield c
    c.close()


def test_yoke_sqlite_file_project_is_ignored_as_invalid_legacy_residue(
    conn, tmp_path: Path
) -> None:
    root = _build_repo(tmp_path, present_modules=["legacy_sqlite_yoke"])
    _seed_governed_yoke(conn, repo_path=root)
    settings = {
        "default_model": "primary",
        "models": {
            "primary": {
                "authoritative_db": {
                    "kind": "sqlite_file",
                    "location": {"path": "data/yoke.db"},
                },
                "runner": {
                    "config": {"modules_dir": "runtime/api/domain/migrations"},
                    "kind": "governed_migration_module",
                },
            }
        },
    }
    conn.execute(
        "UPDATE project_capabilities SET settings=%s WHERE project_id=1",
        (json.dumps(settings),),
    )
    conn.execute(
        "INSERT INTO migration_audit (migration_name, state, started_at) "
        "VALUES ('legacy_sqlite_yoke', 'completed', '2026-04-30T00:00:00Z')"
    )
    conn.commit()

    rec = RecordCollector()
    hc_stranded_migration_module(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"
    assert "legacy_sqlite_yoke" not in rec.results[0].detail


def test_external_root_data_yoke_db_path_is_ignored(conn, tmp_path: Path) -> None:
    repo, migrations, _audit_db = _build_buzz_shape_repo(tmp_path)
    (migrations / "root_named.py").write_text("def apply(c): pass\n")
    root_db = repo / "data" / "yoke.db"
    root_db.parent.mkdir(exist_ok=True)
    _audit_db_with(root_db, name="root_named", state="completed")
    _seed_governed_buzz(conn, repo_path=repo, audit_db_rel="data/yoke.db")

    rec = RecordCollector()
    hc_stranded_migration_module(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"
    assert "root_named" not in rec.results[0].detail

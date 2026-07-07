"""Tests for HC-substrate-project-leak."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_substrate_project_leak import (
    hc_substrate_project_leak,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_SCHEMA = """
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
"""


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(c, ddl)
    return pg_testdb.drop_database_on_close(c, name)


@pytest.fixture
def conn():
    c = _disposable_pg_db(_SCHEMA)
    yield c
    c.close()


def _seed_projects(conn, ids: list[str]) -> None:
    for pid in ids:
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (%s, %s)",
            (pid, pid),
        )
    conn.commit()


def _seed_substrate(repo_root: Path, filenames: list[str]) -> None:
    domain = repo_root / "runtime" / "api" / "domain"
    engines = repo_root / "runtime" / "api" / "engines"
    domain.mkdir(parents=True, exist_ok=True)
    engines.mkdir(parents=True, exist_ok=True)
    for fname in filenames:
        target = domain if fname.startswith("d/") else engines
        target.joinpath(fname.split("/", 1)[1] if "/" in fname else fname).write_text(
            "", encoding="utf-8"
        )


def _run_hc(conn, *, monkeypatch, repo_root: Path) -> RecordCollector:
    rec = RecordCollector()
    args = DoctorArgs()
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_substrate_project_leak._base._resolve_repo_root",
        lambda: str(repo_root),
    )
    hc_substrate_project_leak(conn, args, rec)
    return rec


def test_passes_when_no_non_yoke_projects(conn, monkeypatch, tmp_path):
    _seed_projects(conn, ["yoke"])
    rec = _run_hc(conn, monkeypatch=monkeypatch, repo_root=tmp_path)

    assert len(rec.results) == 1
    assert rec.results[0].check_id == "HC-substrate-project-leak"
    assert rec.results[0].result == "PASS"
    assert "nothing to scan against" in rec.results[0].detail


def test_passes_when_substrate_has_no_project_named_files(
    conn, monkeypatch, tmp_path,
):
    _seed_projects(conn, ["yoke", "buzz"])
    _seed_substrate(
        tmp_path,
        ["d/validate_webapp_pipeline.py", "validate_webapp_pipeline_checks_db.py"],
    )

    rec = _run_hc(conn, monkeypatch=monkeypatch, repo_root=tmp_path)

    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"
    assert rec.results[0].detail == ""


def test_fails_when_substrate_filename_contains_project_id(
    conn, monkeypatch, tmp_path,
):
    project_id = "buzz"
    old_project_named_file = f"validate_{project_id}_pipeline.py"
    _seed_projects(conn, ["yoke", "buzz"])
    _seed_substrate(
        tmp_path,
        [f"d/{old_project_named_file}", "d/validate_webapp_pipeline.py"],
    )

    rec = _run_hc(conn, monkeypatch=monkeypatch, repo_root=tmp_path)

    assert len(rec.results) == 1
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert old_project_named_file in detail
    assert f"'{project_id}'" in detail
    assert "validate_webapp_pipeline.py" not in detail


def test_yoke_named_substrate_files_are_allowed(conn, monkeypatch, tmp_path):
    _seed_projects(conn, ["yoke", "buzz"])
    _seed_substrate(
        tmp_path,
        [
            "d/yoke_operations_cli.py",
            "d/validate_webapp_pipeline.py",
        ],
    )

    rec = _run_hc(conn, monkeypatch=monkeypatch, repo_root=tmp_path)

    assert rec.results[0].result == "PASS"


def test_buzzard_does_not_match_buzz_token(conn, monkeypatch, tmp_path):
    """Token boundary: ``buzz`` should only match identifier-shaped tokens,
    so ``buzzard.py`` and ``buzz_helper.py`` differ in match outcome."""
    _seed_projects(conn, ["yoke", "buzz"])
    _seed_substrate(
        tmp_path,
        ["d/buzzard_helper.py", "d/buzz_helper.py"],
    )

    rec = _run_hc(conn, monkeypatch=monkeypatch, repo_root=tmp_path)

    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "buzz_helper.py" in detail
    assert "buzzard_helper.py" not in detail


def test_self_skips_when_repo_root_cannot_be_resolved(conn, monkeypatch):
    _seed_projects(conn, ["yoke", "buzz"])
    rec = RecordCollector()
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_substrate_project_leak._base._resolve_repo_root",
        lambda: None,
    )
    hc_substrate_project_leak(conn, DoctorArgs(), rec)
    assert rec.results[0].result == "PASS"
    assert "repo root not resolvable" in rec.results[0].detail


def test_passes_when_projects_table_missing(monkeypatch, tmp_path):
    bare_conn = _disposable_pg_db("")
    try:
        rec = _run_hc(bare_conn, monkeypatch=monkeypatch, repo_root=tmp_path)
        assert rec.results[0].result == "PASS"
        assert "nothing to scan against" in rec.results[0].detail
    finally:
        bare_conn.close()

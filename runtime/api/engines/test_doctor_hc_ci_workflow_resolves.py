"""Tests for HC-projects-ci-workflow-resolves."""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.engines.doctor_hc_ci_workflow_resolves import (
    CHECK_ID,
    hc_ci_workflow_declaration_resolves,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _conn(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _schema() -> str:
    return (
        "CREATE TABLE projects ("
        " id INTEGER PRIMARY KEY, "
        " slug TEXT UNIQUE NOT NULL, "
        " github_repo TEXT"
        ");"
        "CREATE TABLE project_capabilities ("
        " project_id INTEGER NOT NULL, "
        " type TEXT NOT NULL, "
        " settings TEXT, "
        " verified_at TEXT, "
        " PRIMARY KEY(project_id, type)"
        ");"
    )


def _record(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_ci_workflow_declaration_resolves(conn, DoctorArgs(), rec)
    return rec


def test_self_skip_when_tables_missing():
    rec = _record(_conn(""))
    assert rec.results == []


def test_pass_when_declared_file_exists(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    workflow = checkout / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    conn = _conn(_schema())
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) "
        "VALUES (7, 'platform', 'upyoke/platform')",
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        'VALUES (7, %s, \'{"workflow_file":"ci.yml"}\')',
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda project_id, **kw: checkout if int(project_id) == 7 else None,
    )

    rec = _record(conn)
    assert rec.results[0].result == "PASS"
    assert rec.results[0].check_id == CHECK_ID
    stamp = conn.execute(
        "SELECT verified_at FROM project_capabilities WHERE project_id = 7",
    ).fetchone()["verified_at"]
    assert stamp


def test_warn_when_declared_file_missing(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    checkout.mkdir()
    conn = _conn(_schema())
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) "
        "VALUES (7, 'platform', 'upyoke/platform')",
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (7, %s, "
        '\'{"workflow_file":"platform-quick-verification.yml"}\')',
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda project_id, **kw: checkout if int(project_id) == 7 else None,
    )

    rec = _record(conn)
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "platform-quick-verification.yml" in detail
    assert "platform" in detail
    assert "upyoke/platform" in detail
    assert "ci_workflow_file" in detail
    assert (
        conn.execute(
            "SELECT verified_at FROM project_capabilities WHERE project_id = 7",
        ).fetchone()["verified_at"]
        is None
    )


def test_pass_when_host_has_no_checkout(monkeypatch):
    conn = _conn(_schema())
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) "
        "VALUES (7, 'platform', 'upyoke/platform')",
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        'VALUES (7, %s, \'{"workflow_file":"absent.yml"}\')',
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda *a, **kw: None,
    )

    rec = _record(conn)
    assert rec.results[0].result == "PASS"

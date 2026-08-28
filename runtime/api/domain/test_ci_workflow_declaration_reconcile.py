"""Checkout reconciliation stamps verified_at only when the file exists."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.ci_workflow_declaration_reconcile import (
    STATUS_MISSING,
    STATUS_NO_CHECKOUT,
    STATUS_RESOLVED,
    STATUS_UNDECLARED,
    reconcile_ci_workflow_declarations,
)
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)


def _conn() -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        conn,
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
        ");",
    )
    return pg_testdb.drop_database_on_close(conn, name)


def _seed(conn, *, workflow_file: str, verified_at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) "
        "VALUES (7, 'platform', 'upyoke/platform')",
    )
    conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, settings, verified_at) VALUES "
        "(%s, %s, %s, %s)",
        (
            7,
            CI_WORKFLOW_CAPABILITY_TYPE,
            '{"workflow_file":"%s"}' % workflow_file,
            verified_at,
        ),
    )


def _verified_at(conn) -> str | None:
    row = conn.execute(
        "SELECT verified_at FROM project_capabilities "
        "WHERE project_id = 7 AND type = %s",
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    ).fetchone()
    return row["verified_at"]


def test_missing_file_clears_verified_at(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    checkout.mkdir()
    conn = _conn()
    _seed(conn, workflow_file="platform-quick-verification.yml")
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda project_id, **kw: checkout if int(project_id) == 7 else None,
    )

    results = reconcile_ci_workflow_declarations(conn)

    assert results[0]["status"] == STATUS_MISSING
    assert results[0]["workflow_file"] == "platform-quick-verification.yml"
    assert _verified_at(conn) is None


def test_present_file_stamps_verified_at(tmp_path, monkeypatch):
    checkout = tmp_path / "platform"
    workflow = checkout / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: ci\n", encoding="utf-8")
    conn = _conn()
    _seed(conn, workflow_file="ci.yml")
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda project_id, **kw: checkout if int(project_id) == 7 else None,
    )

    results = reconcile_ci_workflow_declarations(conn)

    assert results[0]["status"] == STATUS_RESOLVED
    stamp = _verified_at(conn)
    assert stamp
    assert "T" in stamp


def test_no_checkout_leaves_unverified(monkeypatch):
    conn = _conn()
    _seed(conn, workflow_file="ci.yml")
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda *a, **kw: None,
    )

    results = reconcile_ci_workflow_declarations(conn)

    assert results[0]["status"] == STATUS_NO_CHECKOUT
    assert _verified_at(conn) is None


def test_empty_workflow_file_is_undeclared(monkeypatch):
    conn = _conn()
    _seed(conn, workflow_file="")
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda *a, **kw: Path("/unused"),
    )

    results = reconcile_ci_workflow_declarations(conn)

    assert results[0]["status"] == STATUS_UNDECLARED
    assert _verified_at(conn) is None


@pytest.mark.parametrize("github_repo", ["upyoke/platform"])
def test_missing_result_names_repo(tmp_path, monkeypatch, github_repo):
    checkout = tmp_path / "platform"
    checkout.mkdir()
    conn = _conn()
    _seed(conn, workflow_file="absent.yml")
    monkeypatch.setattr(
        "yoke_core.domain.ci_workflow_declaration_reconcile.checkout_for_project_id",
        lambda project_id, **kw: checkout if int(project_id) == 7 else None,
    )

    results = reconcile_ci_workflow_declarations(conn)

    assert results[0]["github_repo"] == github_repo
    assert results[0]["status"] == STATUS_MISSING

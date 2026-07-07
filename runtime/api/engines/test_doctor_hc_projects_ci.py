"""Tests for HC-projects-ci-workflow-configured.

Covers: silent self-skip on missing tables, PASS when no projects
declare ``github_repo``, PASS when every qualifying project declares the
capability, WARN listing the projects that do not.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)
from yoke_core.engines.doctor_hc_projects_ci import (
    CHECK_ID,
    hc_projects_ci_workflow_configured,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _make_conn() -> Any:
    return _disposable_pg_db(
        "CREATE TABLE projects ("
        " id INTEGER PRIMARY KEY, "
        " slug TEXT UNIQUE NOT NULL, "
        " github_repo TEXT"
        ");"
        "CREATE TABLE project_capabilities ("
        " project_id INTEGER NOT NULL, "
        " type TEXT NOT NULL, "
        " settings TEXT, "
        " PRIMARY KEY(project_id, type)"
        ");"
    )


def _record(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_projects_ci_workflow_configured(conn, DoctorArgs(), rec)
    return rec


def test_self_skip_when_projects_table_missing():
    conn = _disposable_pg_db("")
    rec = _record(conn)
    assert rec.results == []


def test_self_skip_when_capabilities_table_missing():
    conn = _disposable_pg_db(
        "CREATE TABLE projects (id INTEGER, slug TEXT, github_repo TEXT)"
    )
    rec = _record(conn)
    assert rec.results == []


def test_pass_when_no_projects_declare_github_repo():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) VALUES (1, 'local', NULL)",
    )
    rec = _record(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"
    assert rec.results[0].check_id == CHECK_ID


def test_pass_when_every_qualifying_project_has_capability():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) VALUES "
        " (1, 'yoke', 'upyoke/yoke'),"
        " (2, 'buzz', 'example-org/buzz')",
    )
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) VALUES "
        " (1, %s, '{\"workflow_file\":\"yoke-ci.yml\"}'),"
        " (2, %s, '{\"workflow_file\":\"buzz-ci.yml\"}')",
        (CI_WORKFLOW_CAPABILITY_TYPE, CI_WORKFLOW_CAPABILITY_TYPE),
    )
    rec = _record(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"
    assert CI_WORKFLOW_CAPABILITY_TYPE in rec.results[0].detail


def test_warn_lists_missing_projects():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) VALUES "
        " (1, 'yoke', 'upyoke/yoke'),"
        " (2, 'buzz', 'example-org/buzz')",
    )
    # Only yoke has the capability; buzz is missing.
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (1, %s, '{\"workflow_file\":\"yoke-ci.yml\"}')",
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    rec = _record(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "WARN"
    assert "buzz" in rec.results[0].detail
    assert "yoke" not in rec.results[0].detail.split("Projects with github_repo")[1].split("\n")[0]


def test_warn_lists_multiple_missing_projects_alphabetically():
    conn = _make_conn()
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) VALUES "
        " (1, 'zeta', 'owner/zeta'),"
        " (2, 'alpha', 'owner/alpha'),"
        " (3, 'mike', 'owner/mike')",
    )
    rec = _record(conn)
    assert len(rec.results) == 1
    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    # Projects iterated in alphabetical order via ORDER BY slug.
    assert detail.index("alpha") < detail.index("mike") < detail.index("zeta")


@pytest.mark.parametrize("github_repo", ["", None])
def test_empty_github_repo_excluded_from_qualifying_set(github_repo):
    conn = _make_conn()
    conn.execute(
        "INSERT INTO projects (id, slug, github_repo) VALUES (%s, %s, %s)",
        (1, "local", github_repo),
    )
    rec = _record(conn)
    assert rec.results[0].result == "PASS"

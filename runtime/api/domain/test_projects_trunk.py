"""Tests for :mod:`yoke_core.domain.projects_trunk`.

The trunk resolves through the integration-trunk satisfier ladder:
the operator's declared ``projects.default_branch`` first, then the
default branch the recorded remote reports (converged into
``project_derived_facts``), and a named refusal when neither answers.
There is no ``"main"`` fallback — that guess is what let work anchor to
a base nobody chose.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.projects_trunk import (
    ProjectNotFound,
    TrunkUnspecified,
    resolve_trunk,
    resolve_trunk_safe,
)


def _empty_db_conn() -> Any:
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )


@pytest.fixture
def conn() -> Iterator[Any]:
    c = _empty_db_conn()
    c.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
        "default_branch TEXT DEFAULT 'main')"
    )
    yield c
    c.close()


@pytest.fixture
def conn_with_derived(conn) -> Iterator[Any]:
    conn.execute(
        "CREATE TABLE project_derived_facts (project_id INTEGER, "
        "fact_key TEXT, present INTEGER, fact_value TEXT, "
        "observed_at TEXT, observed_from TEXT)"
    )
    yield conn


def test_resolve_trunk_reads_declared_value(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', 'trunk')"
    )
    assert resolve_trunk(conn, 100) == "trunk"


def test_resolve_trunk_strips_whitespace(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) "
        "VALUES (100, 'alpha', '  trunk  ')"
    )
    assert resolve_trunk(conn, 100) == "trunk"


def test_null_declared_branch_refuses_instead_of_guessing_main(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', NULL)"
    )
    with pytest.raises(TrunkUnspecified) as excinfo:
        resolve_trunk(conn, 100)
    assert "integration_trunk" in str(excinfo.value)
    assert "--default-branch" in str(excinfo.value)


def test_blank_declared_branch_refuses(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', '   ')"
    )
    with pytest.raises(TrunkUnspecified):
        resolve_trunk(conn, 100)


def test_refusal_names_every_rung_it_considered(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', '')"
    )
    with pytest.raises(TrunkUnspecified) as excinfo:
        resolve_trunk(conn, 100)
    message = str(excinfo.value)
    assert "declared_default_branch" in message
    assert "derived_default_branch" in message


def test_derived_branch_satisfies_the_lower_rung(conn_with_derived):
    conn_with_derived.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', NULL)"
    )
    conn_with_derived.execute(
        "INSERT INTO project_derived_facts "
        "(project_id, fact_key, present, fact_value, observed_at, observed_from) "
        "VALUES (100, 'default_branch', 1, 'trunk', 'now', 'binding')"
    )
    assert resolve_trunk(conn_with_derived, 100) == "trunk"


def test_declared_branch_outranks_derived(conn_with_derived):
    conn_with_derived.execute(
        "INSERT INTO projects (id, slug, default_branch) "
        "VALUES (100, 'alpha', 'declared')"
    )
    conn_with_derived.execute(
        "INSERT INTO project_derived_facts "
        "(project_id, fact_key, present, fact_value, observed_at, observed_from) "
        "VALUES (100, 'default_branch', 1, 'derived', 'now', 'binding')"
    )
    assert resolve_trunk(conn_with_derived, 100) == "declared"


def test_resolve_trunk_raises_when_project_row_missing(conn):
    with pytest.raises(ProjectNotFound):
        resolve_trunk(conn, 999)


def test_resolve_trunk_safe_returns_none_when_project_row_missing(conn):
    assert resolve_trunk_safe(conn, 999) is None


def test_resolve_trunk_safe_returns_none_when_no_rung_resolves(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', NULL)"
    )
    assert resolve_trunk_safe(conn, 100) is None


def test_resolve_trunk_safe_returns_value_when_set(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) "
        "VALUES (100, 'alpha', 'develop')"
    )
    assert resolve_trunk_safe(conn, 100) == "develop"


def test_resolve_trunk_safe_returns_none_when_projects_table_missing():
    c = _empty_db_conn()
    try:
        assert resolve_trunk_safe(c, 100) is None
    finally:
        c.close()


def test_resolve_trunk_raises_project_not_found_when_table_missing():
    c = _empty_db_conn()
    try:
        with pytest.raises(ProjectNotFound):
            resolve_trunk(c, 100)
    finally:
        c.close()

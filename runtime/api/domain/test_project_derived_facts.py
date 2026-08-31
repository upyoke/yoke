"""Derived project facts converge from control-plane state at snapshot sync.

An absent row means UNKNOWN downstream, never "false" — so these check
both what each observer reports and that a missing table degrades to a
warning rather than to a confident negative.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.gate_satisfier_facts import (
    DERIVED_ENVIRONMENTS_PRESENT,
    FactVerdict,
    load_project_facts,
)
from yoke_core.domain.project_derived_facts import (
    DERIVED_FACT_KEYS,
    FACT_DEFAULT_BRANCH,
    FACT_ENVIRONMENTS_PRESENT,
    FACT_REMOTE_PRESENT,
    FACT_TEST_COMMAND_DECLARED,
    converge_derived_facts,
    observe_now,
)


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    c.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
        "github_repo TEXT, default_branch TEXT)"
    )
    c.execute(
        "CREATE TABLE project_github_repo_bindings (project_id INTEGER, "
        "github_repo TEXT, default_branch TEXT, status TEXT)"
    )
    c.execute("CREATE TABLE environments (id INTEGER, project_id INTEGER)")
    c.execute(
        "CREATE TABLE qa_plans (id INTEGER PRIMARY KEY, retired_at TEXT)"
    )
    c.execute(
        "CREATE TABLE qa_plan_project_defaults (project_id INTEGER, "
        "plan_id INTEGER)"
    )
    c.execute(
        "CREATE TABLE project_derived_facts (id SERIAL PRIMARY KEY, "
        "project_id INTEGER, fact_key TEXT, present INTEGER, "
        "fact_value TEXT, observed_at TEXT, observed_from TEXT)"
    )
    c.execute("INSERT INTO projects (id, slug) VALUES (1, 'alpha')")
    c.commit()
    yield c
    c.close()


def _facts(conn) -> dict:
    return converge_derived_facts(conn, 1)["facts"]


def test_a_bare_project_reports_every_fact_absent(conn):
    facts = _facts(conn)
    assert facts[FACT_REMOTE_PRESENT]["present"] is False
    assert facts[FACT_DEFAULT_BRANCH]["present"] is False
    assert facts[FACT_TEST_COMMAND_DECLARED]["present"] is False
    assert facts[FACT_ENVIRONMENTS_PRESENT]["present"] is False


def test_an_active_repo_binding_supplies_remote_and_default_branch(conn):
    conn.execute(
        "INSERT INTO project_github_repo_bindings "
        "(project_id, github_repo, default_branch, status) "
        "VALUES (1, 'owner/repo', 'trunk', 'active')"
    )
    conn.commit()
    facts = _facts(conn)
    assert facts[FACT_REMOTE_PRESENT] == {
        "present": True, "value": "owner/repo",
    }
    assert facts[FACT_DEFAULT_BRANCH] == {"present": True, "value": "trunk"}


def test_a_declared_github_repo_alone_still_counts_as_a_remote(conn):
    conn.execute("UPDATE projects SET github_repo = 'owner/repo' WHERE id = 1")
    conn.commit()
    assert _facts(conn)[FACT_REMOTE_PRESENT]["present"] is True


def test_an_inactive_binding_does_not_supply_a_default_branch(conn):
    conn.execute(
        "INSERT INTO project_github_repo_bindings "
        "(project_id, github_repo, default_branch, status) "
        "VALUES (1, 'owner/repo', 'trunk', 'revoked')"
    )
    conn.commit()
    assert _facts(conn)[FACT_DEFAULT_BRANCH]["present"] is False


def test_a_live_project_default_plan_declares_a_test_command(conn):
    conn.execute("INSERT INTO qa_plans (id, retired_at) VALUES (5, NULL)")
    conn.execute(
        "INSERT INTO qa_plan_project_defaults (project_id, plan_id) "
        "VALUES (1, 5)"
    )
    conn.commit()
    assert _facts(conn)[FACT_TEST_COMMAND_DECLARED]["present"] is True


def test_a_retired_plan_does_not_declare_a_test_command(conn):
    conn.execute("INSERT INTO qa_plans (id, retired_at) VALUES (5, 'gone')")
    conn.execute(
        "INSERT INTO qa_plan_project_defaults (project_id, plan_id) "
        "VALUES (1, 5)"
    )
    conn.commit()
    assert _facts(conn)[FACT_TEST_COMMAND_DECLARED]["present"] is False


def test_registered_environments_are_reported(conn):
    conn.execute("INSERT INTO environments (id, project_id) VALUES (9, 1)")
    conn.commit()
    assert _facts(conn)[FACT_ENVIRONMENTS_PRESENT]["present"] is True


def test_rows_are_replaced_rather_than_appended_on_reconvergence(conn):
    converge_derived_facts(conn, 1)
    conn.execute("INSERT INTO environments (id, project_id) VALUES (9, 1)")
    conn.commit()
    converge_derived_facts(conn, 1)
    row = conn.execute(
        "SELECT COUNT(*), MAX(present) FROM project_derived_facts "
        "WHERE project_id = 1 AND fact_key = %s",
        (FACT_ENVIRONMENTS_PRESENT,),
    ).fetchone()
    assert row[0] == 1
    assert int(row[1]) == 1


def test_an_unconverged_store_reports_unstored_without_warning(conn):
    """The store arrives with the boot converge; that is not a fault.

    Readers fall back to a live observation until it exists, so warning
    on every sync of a not-yet-booted database would be noise about a
    state nothing is waiting on.
    """
    conn.execute("DROP TABLE project_derived_facts")
    conn.commit()
    warnings: list[str] = []
    result = converge_derived_facts(conn, 1, warnings)
    assert result["stored"] is False
    assert result["facts"][FACT_REMOTE_PRESENT]["present"] is False
    assert warnings == []


def test_every_declared_fact_key_has_an_observer(conn):
    for fact_key in DERIVED_FACT_KEYS:
        assert observe_now(conn, 1, fact_key) is not None


def test_an_unknown_fact_key_has_no_observer(conn):
    assert observe_now(conn, 1, "invented_fact") is None


def test_an_unconverged_project_observes_live_rather_than_reading_unknown(conn):
    """A project that has never synced must not refuse correct work.

    Convergence is the normal source, but treating its absence as
    unknown would block a transition for a reason the operator did
    nothing to cause, so the fact is observed on the spot instead.
    """
    conn.execute("INSERT INTO environments (id, project_id) VALUES (9, 1)")
    conn.commit()
    facts = load_project_facts(conn, 1)
    assert facts.verdict(DERIVED_ENVIRONMENTS_PRESENT) is FactVerdict.PRESENT
    assert "not yet converged" in facts.explain(DERIVED_ENVIRONMENTS_PRESENT)


def test_a_converged_row_wins_over_a_live_observation(conn):
    converge_derived_facts(conn, 1)
    facts = load_project_facts(conn, 1)
    assert facts.verdict(DERIVED_ENVIRONMENTS_PRESENT) is FactVerdict.ABSENT
    assert "not yet converged" not in facts.explain(DERIVED_ENVIRONMENTS_PRESENT)


def test_an_absent_store_still_answers_from_a_live_observation(conn):
    conn.execute("DROP TABLE project_derived_facts")
    conn.execute("INSERT INTO environments (id, project_id) VALUES (9, 1)")
    conn.commit()
    facts = load_project_facts(conn, 1)
    assert facts.verdict(DERIVED_ENVIRONMENTS_PRESENT) is FactVerdict.PRESENT

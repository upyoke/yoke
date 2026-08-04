"""Boot convergence against a universe's own stored definitions.

Convergence registers the built-in workflows and makes the current definition
available at the universe's own next version number. It never rewrites a
stored row, never renumbers one, never deletes one, and never refuses to boot
over a definition it does not recognize -- that refusal took the fleet down
twice. What it will not do either is decide what a universe runs: selecting a
version is a separate, deliberate act.
"""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import builtin_workflow_version_convergence, db_helpers
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definition,
    builtin_workflow_version_history,
)
from yoke_core.domain.builtin_workflow_version_convergence import (
    unrecognized_builtin_versions,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_registry import (
    converge_builtin_workflows,
    list_current_workflows,
    publish_workflow_version,
    select_current_builtin_workflow_versions,
)
from yoke_core.domain.workflow_schema import ensure_workflow_registry_tables

_TS = "2026-07-25T00:00:00Z"


def _definition(workflow_id: str = "issue") -> dict:
    return builtin_workflow_definition(workflow_id)["definition"]


def _seed_first_generation(conn, fixtures) -> None:
    """Stand the universe up holding only each workflow's first generation."""
    conn.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    selected = [
        fixture for fixture in fixtures if int(fixture["canon_version"]) == 1
    ] or list(fixtures)
    for fixture in selected:
        workflow = fixture["workflow"]
        definition = fixture["definition"]
        workflow_values = tuple(
            workflow[key] for key in ("id", "name", "description", "source")
        )
        conn.execute(
            "INSERT INTO workflows "
            "(id, name, description, source, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
            workflow_values + (_TS, _TS),
        )
        version_id = conn.execute(
            "INSERT INTO workflow_versions "
            "(workflow_id, version, definition_schema_version, "
            "definition_json, definition_digest, published_at, immutable_at) "
            "VALUES (%s, 1, 1, %s, %s, %s, %s) RETURNING id",
            (workflow["id"], canonical_definition_json(definition),
             definition_digest(definition), _TS, _TS),
        ).fetchone()[0]
        conn.execute(
            "UPDATE workflows SET current_version_id = %s WHERE id = %s",
            (version_id, workflow["id"]),
        )
    conn.commit()


def _first_generation_rows(conn) -> list[tuple]:
    rows = conn.execute(
        "SELECT workflow_id, definition_json, definition_digest "
        "FROM workflow_versions WHERE version = 1 ORDER BY workflow_id"
    ).fetchall()
    return [tuple(row.values()) for row in rows]


def test_convergence_appends_the_current_definition_without_rewriting(
    test_db,
):
    """A universe holding an older generation keeps it and gains the new one."""
    _seed_first_generation(test_db, builtin_workflow_version_history())
    expected_dash = builtin_workflow_definition("dash")["workflow"]
    test_db.execute(
        "UPDATE workflows SET name = 'Old', description = 'Old' "
        "WHERE id = 'dash'"
    )
    before = _first_generation_rows(test_db)

    converge_builtin_workflows(test_db)

    # The stored generation is untouched; the current definition arrives as a
    # new row at this universe's own next number.
    assert _first_generation_rows(test_db) == before
    dash_copy = test_db.execute(
        "SELECT name, description FROM workflows WHERE id = 'dash'"
    ).fetchone()
    assert tuple(dash_copy) == (expected_dash["name"], expected_dash["description"])
    workflows = list_current_workflows(test_db)
    assert all(
        [version["version"] for version in row["versions"]] == [1, 2]
        for row in workflows
    )
    # Convergence makes the definition available; it does not decide what a
    # universe runs. What was selected stays selected.
    assert {row["current_version"] for row in workflows} == {1}
    # Both rows are published generations, recognized by content rather than
    # by sitting at the number the code expected.
    assert all(
        version["provenance"]["kind"] == "canon"
        for row in workflows
        for version in row["versions"]
    )

    # Re-selecting finds the row it just appended rather than adding another.
    selected = select_current_builtin_workflow_versions(test_db)
    assert set(selected.values()) == {2}
    assert {
        row["current_version"] for row in list_current_workflows(test_db)
    } == {2}


def test_an_unrecognized_definition_is_reported_not_refused(test_db):
    """The change that ended two fleet-wide outages.

    A stored definition the canon does not recognize is either a local
    customization or real corruption, and convergence cannot tell which. It is
    a fact about one universe, so it surfaces in that universe's health report
    instead of aborting a boot that runs for every tenant.
    """
    fixtures = builtin_workflow_version_history()
    fixtures[0]["definition"]["stages"][0]["label"] = "Unknown drift"
    drifted_workflow = str(fixtures[0]["workflow"]["id"])
    _seed_first_generation(test_db, fixtures)

    converge_builtin_workflows(test_db)

    findings = unrecognized_builtin_versions(test_db)
    assert [
        (row["workflow_id"], row["version"]) for row in findings
    ] == [(drifted_workflow, 1)]
    # The universe still boots, still keeps the row it had, and still gains
    # the current definition alongside it.
    stored = {
        row["id"]: [version["version"] for version in row["versions"]]
        for row in list_current_workflows(test_db)
    }
    assert stored[drifted_workflow] == [1, 2]


def test_builtin_convergence_keeps_sqlite_locking_portable():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        ensure_workflow_registry_tables(conn)
        converge_builtin_workflows(conn)
        converge_builtin_workflows(conn)
        # Convergence is idempotent: the second run recognizes its own row by
        # digest rather than appending a duplicate.
        assert {
            (row["id"], row["current_version"], len(row["versions"]))
            for row in list_current_workflows(conn)
        } == {(workflow_id, 1, 1) for workflow_id in BUILTIN_WORKFLOW_IDS}


def test_selection_locks_before_digest_lookup(test_db, monkeypatch):
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("digest lookup ran before the workflow lock")

    monkeypatch.setattr(
        builtin_workflow_version_convergence,
        "_matching_version",
        unexpected_lookup,
    )
    test_db.execute("SELECT id FROM workflows WHERE id = 'issue' FOR UPDATE")
    with db_helpers.connect() as contender:
        contender.execute("SET LOCAL lock_timeout = '100ms'")
        with pytest.raises(Exception, match="lock timeout"):
            select_current_builtin_workflow_versions(contender)
        contender.rollback()
    test_db.rollback()


def test_convergence_leaves_an_operator_edit_in_place(test_db):
    """A universe editing its own definitions is the supported case.

    The operator's version occupies the number the code would once have
    claimed for itself. Nothing collides, because the code no longer owns a
    number -- it appends the current definition after whatever is there.
    """
    _seed_first_generation(test_db, builtin_workflow_version_history())
    changed = _definition()
    changed["stages"][0]["label"] = "Operator filed"
    operator_version = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=changed,
        published_by_actor_id=1,
    )
    assert operator_version["version"] == 2

    converge_builtin_workflows(test_db)

    issue = next(
        row for row in list_current_workflows(test_db) if row["id"] == "issue"
    )
    assert [version["version"] for version in issue["versions"]] == [1, 2, 3]
    edited = next(
        version for version in issue["versions"] if version["version"] == 2
    )
    assert edited["provenance"] == {"kind": "local"}
    # The operator's edit is still what this universe runs, so its status is
    # customized -- convergence appended the newer published definition
    # without overriding the choice.
    assert issue["current_version"] == 2
    assert issue["canon_status"]["state"] == "customized"

"""Resolution and row-write behavior for workflow execution instructions."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import workflow_execution_instructions as instructions
from yoke_core.domain.workflow_execution_instructions_schema import (
    INSTRUCTION_PROJECTS_TABLE,
    INSTRUCTION_WORKFLOWS_TABLE,
    WORKFLOW_EXECUTION_INSTRUCTIONS_TABLES_SQL,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE workflows (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE items (
          id INTEGER PRIMARY KEY, workflow_id TEXT, project_id INTEGER
        );
        """
    )
    conn.executescript(WORKFLOW_EXECUTION_INSTRUCTIONS_TABLES_SQL)
    conn.execute("INSERT INTO workflows VALUES ('dash', 'Dash')")
    conn.execute("INSERT INTO workflows VALUES ('issue', 'Issue')")
    conn.execute("INSERT INTO projects VALUES (1, 'yoke')")
    conn.execute("INSERT INTO projects VALUES (2, 'acme')")
    conn.execute("INSERT INTO items VALUES (5, 'dash', 1)")
    return conn


def _seed(
    conn: sqlite3.Connection,
    *,
    title: str,
    workflow_ids: list[str],
    all_projects: bool = False,
    project_ids: list[int] | None = None,
    ordering: int = 0,
    status: str = "active",
) -> int:
    instruction_id = instructions.create_instruction(
        conn, title=title, content=f"{title} content", ordering=ordering,
        status=status,
    )
    instructions.set_instruction_scope(
        conn,
        instruction_id,
        workflow_ids=workflow_ids,
        applies_to_all_projects=all_projects,
        project_ids=project_ids or [],
    )
    return instruction_id


def test_resolution_orders_general_to_specific_with_deterministic_ties():
    conn = _connection()
    project_scoped = _seed(
        conn, title="Project scoped", workflow_ids=["dash"],
        project_ids=[1], ordering=0,
    )
    all_late = _seed(
        conn, title="All projects late", workflow_ids=["dash", "issue"],
        all_projects=True, ordering=5,
    )
    all_early = _seed(
        conn, title="All projects early", workflow_ids=["dash"],
        all_projects=True, ordering=5,
    )

    resolved = instructions.resolve_execution_instructions(
        conn, workflow_id="dash", project_id=1
    )

    # All-projects rows precede project-scoped rows regardless of ordering;
    # equal (group, ordering) falls back to id.
    assert [row["id"] for row in resolved] == [
        all_late, all_early, project_scoped,
    ]
    assert resolved[0]["applies_to_all_projects"] is True
    assert resolved[-1]["applies_to_all_projects"] is False


def test_resolution_filters_by_workflow_project_and_status():
    conn = _connection()
    _seed(
        conn, title="Wrong workflow", workflow_ids=["issue"],
        all_projects=True,
    )
    _seed(
        conn, title="Wrong project", workflow_ids=["dash"], project_ids=[2],
    )
    _seed(
        conn, title="Disabled", workflow_ids=["dash"], all_projects=True,
        status="disabled",
    )
    visible = _seed(
        conn, title="Visible", workflow_ids=["dash"], project_ids=[1],
    )

    resolved = instructions.resolve_execution_instructions(
        conn, workflow_id="dash", project_id=1
    )

    assert [row["id"] for row in resolved] == [visible]


def test_resolve_for_item_reads_the_pinned_workflow_and_project():
    conn = _connection()
    matched = _seed(
        conn, title="Dash on yoke", workflow_ids=["dash"], project_ids=[1],
    )
    _seed(conn, title="Acme only", workflow_ids=["dash"], project_ids=[2])

    resolved = instructions.resolve_for_item(conn, 5)

    assert [row["id"] for row in resolved] == [matched]
    assert instructions.resolve_for_item(conn, 999) == []


def test_all_projects_predicate_covers_projects_without_junction_rows():
    conn = _connection()
    covering = _seed(
        conn, title="Everywhere", workflow_ids=["dash"], all_projects=True,
    )
    # A project created after the instruction has no junction rows, yet the
    # stored predicate covers it with zero backfill.
    conn.execute("INSERT INTO projects VALUES (3, 'newest')")

    resolved = instructions.resolve_execution_instructions(
        conn, workflow_id="dash", project_id=3
    )

    assert [row["id"] for row in resolved] == [covering]


def test_set_scope_replaces_bindings_and_list_reports_them():
    conn = _connection()
    instruction_id = _seed(
        conn, title="Scoped", workflow_ids=["dash", "issue"],
        project_ids=[1, 2],
    )
    instructions.set_instruction_scope(
        conn, instruction_id, workflow_ids=["issue"],
        applies_to_all_projects=True, project_ids=[2],
    )

    listed = instructions.list_instructions(conn)

    assert len(listed) == 1
    row = listed[0]
    assert row["workflow_ids"] == ["issue"]
    assert row["project_ids"] == [2]
    assert row["applies_to_all_projects"] is True


def test_update_guards_blank_fields_and_unknown_ids():
    conn = _connection()
    instruction_id = _seed(conn, title="Guarded", workflow_ids=["dash"])

    with pytest.raises(instructions.EmptyExecutionInstructionError):
        instructions.update_instruction(conn, instruction_id, content="  ")
    with pytest.raises(instructions.UnknownExecutionInstructionError):
        instructions.update_instruction(conn, 999, title="Nope")
    with pytest.raises(instructions.EmptyExecutionInstructionError):
        instructions.create_instruction(conn, title=" ", content="x")

    instructions.update_instruction(
        conn, instruction_id, title="Renamed", status="disabled",
    )
    row = instructions.list_instructions(conn)[0]
    assert row["title"] == "Renamed"
    assert row["status"] == "disabled"


def test_delete_removes_the_row_and_its_scope_bindings():
    conn = _connection()
    instruction_id = _seed(
        conn, title="Doomed", workflow_ids=["dash"], project_ids=[1],
    )

    instructions.delete_instruction(conn, instruction_id)

    assert instructions.list_instructions(conn) == []
    for table in (INSTRUCTION_WORKFLOWS_TABLE, INSTRUCTION_PROJECTS_TABLE):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0
    with pytest.raises(instructions.UnknownExecutionInstructionError):
        instructions.delete_instruction(conn, instruction_id)

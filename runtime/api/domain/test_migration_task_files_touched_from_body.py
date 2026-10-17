"""The history entry that moves task file rows into each body's section."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.task_files_touched import (
    STATE_NO_FILES,
    STATE_PATHS,
    parse_files_touched,
)


ENTRY_NAME = "0083_task_files_touched_from_body"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _legacy(tasks, rows) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE epic_tasks (id INTEGER PRIMARY KEY, epic_id INTEGER, "
        "task_num INTEGER, body TEXT, scope_state TEXT NOT NULL DEFAULT 'pending', "
        "scope_finalized_at TEXT, UNIQUE(epic_id, task_num));"
        "CREATE TABLE epic_task_files (id INTEGER PRIMARY KEY, epic_id INTEGER, "
        "task_num INTEGER, file_path TEXT NOT NULL, action TEXT);"
    )
    conn.executemany(
        "INSERT INTO epic_tasks (epic_id, task_num, body, scope_state) "
        "VALUES (?, ?, ?, ?)",
        tasks,
    )
    conn.executemany(
        "INSERT INTO epic_task_files (epic_id, task_num, file_path, action) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    return conn


def _body(conn, task_num: int) -> str:
    return conn.execute(
        "SELECT body FROM epic_tasks WHERE epic_id=7 AND task_num=?", (task_num,)
    ).fetchone()[0]


def test_entry_declares_its_serving_floor() -> None:
    assert entry.MINIMUM_SERVING_VERSION == NEXT_RELEASE
    assert declared_minimum(entry) == NEXT_RELEASE


def test_matching_section_is_left_exactly_as_written() -> None:
    body = "# Task\n\n## Files Touched\n- `src/a.py` (modify — keep core)\n"
    conn = _legacy([(7, 1, body, "paths")], [(7, 1, "src/a.py", "modify")])

    entry.apply(conn)

    assert _body(conn, 1) == body


def test_rows_replace_a_stale_section_and_keep_every_old_fact() -> None:
    body = (
        "# Task\n\n## Files Touched\n- `src/old.py` (modify)\n\n"
        "## Watch Out For\nStay small.\n"
    )
    conn = _legacy(
        [(7, 1, body, "paths")],
        [
            (7, 1, "src/new.py", "create"),
            (7, 1, "src/a.py", "regenerated from the template"),
            (7, 1, "~/outside/deploy.sh", "modify"),
        ],
    )

    entry.apply(conn)

    rewritten = _body(conn, 1)
    parsed = parse_files_touched(rewritten)
    assert parsed.state == STATE_PATHS
    assert parsed.paths == ("src/new.py", "src/a.py")
    assert "- create `src/new.py`\n- modify `src/a.py`" in rewritten
    superseded = rewritten.split(entry.SUPERSEDED_HEADING, 1)[1]
    assert "`src/old.py` (modify)" in superseded
    assert "`src/a.py` — regenerated from the template" in superseded
    assert "`~/outside/deploy.sh` — modify" in superseded
    assert rewritten.index("## Watch Out For") > rewritten.index(
        entry.SUPERSEDED_HEADING
    )


def test_task_without_a_section_gains_one_from_its_rows() -> None:
    conn = _legacy([(7, 1, "Do the thing.", "paths")], [(7, 1, "src/a.py", "")])

    entry.apply(conn)

    assert parse_files_touched(_body(conn, 1)).paths == ("src/a.py",)


def test_no_files_task_gets_the_explicit_line_and_pending_task_is_untouched() -> None:
    conn = _legacy(
        [(7, 1, "Docs only.", "no_files"), (7, 2, "Planned later.", "pending")],
        [],
    )

    entry.apply(conn)

    assert parse_files_touched(_body(conn, 1)).state == STATE_NO_FILES
    assert _body(conn, 2) == "Planned later."


def test_rows_with_no_repository_path_become_the_no_files_line() -> None:
    conn = _legacy([(7, 1, "", "paths")], [(7, 1, "~/buzz/sync.sh", "modify")])

    entry.apply(conn)

    body = _body(conn, 1)
    assert parse_files_touched(body).state == STATE_NO_FILES
    assert "`~/buzz/sync.sh` — modify" in body


def test_entry_drops_the_rows_and_scope_columns_and_proves_it() -> None:
    conn = _legacy([(7, 1, "", "paths")], [(7, 1, "src/a.py", "modify")])

    entry.apply(conn)
    entry.invariants(conn)

    assert not _table_exists(conn, "epic_task_files")
    for column in entry.RETIRED_COLUMNS:
        assert not _column_exists(conn, "epic_tasks", column)


def test_rerun_on_a_converged_database_changes_nothing() -> None:
    conn = _legacy([(7, 1, "", "paths")], [(7, 1, "src/a.py", "modify")])
    entry.apply(conn)
    body = _body(conn, 1)

    entry.apply(conn)

    assert _body(conn, 1) == body


def test_mismatch_aborts_before_anything_is_dropped(monkeypatch) -> None:
    conn = _legacy([(7, 1, "", "paths")], [(7, 1, "src/a.py", "modify")])
    monkeypatch.setattr(entry, "_rewrite", lambda body, entries, rows: body)

    with pytest.raises(entry.TaskFilesRewriteMismatch, match="nothing was dropped"):
        entry.apply(conn)

    assert _table_exists(conn, "epic_task_files")
    assert _column_exists(conn, "epic_tasks", "scope_state")

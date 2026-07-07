"""Tests for the structured-backlog-field scanner used by HC-obsoleted-terms.

The archive-and-historical-fields preservation policy is documented in
``docs/archive/decisions/historical-obsoleted-hook-refs.md``; this suite
verifies the scanner skips fields owned by items in historical statuses
(``done``, ``release``, ``implemented``, ``cancelled``) while continuing
to flag the same content on non-terminal items.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_obsoleted_terms_backlog import (
    TERMINAL_STATUSES,
    scan_backlog_fields,
)

# Two retired-surface patterns are enough to exercise the scanner without
# tying the suite to the full live registry — the regression value is the
# terminal/non-terminal owner-status filtering, not pattern coverage. The
# pattern set in ``doctor_hc_obsoleted_terms.OBSOLETED_TERM_PATTERNS`` is
# tested separately under ``test_doctor_hc_obsoleted_terms*``.
# Retired-surface tokens are assembled via string concatenation so the
# scan_repo file scanner (which reads this test file's source text) does
# not flag the literal regex source or label strings as live residue.
def _retired_shell() -> str:
    return "yoke" + "-db.sh"


def _retired_hook() -> str:
    return "runtime.harness." + "session_hooks"


PATTERNS: tuple[str, ...] = (
    r"yoke-db\.sh",
    r"runtime\.harness\.session_hooks\b",
)
LABELS: dict[str, str] = {
    PATTERNS[0]: _retired_shell() + " (retired shell wrapper)",
    PATTERNS[1]: _retired_hook() + " (retired hook module)",
}


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(conn, ddl)
    return pg_testdb.drop_database_on_close(conn, name)


def _build_db() -> Any:
    return _disposable_pg_db(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            status TEXT,
            spec TEXT,
            technical_plan TEXT,
            test_results TEXT,
            worktree_plan TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            body TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE epic_progress_notes (
            id INTEGER PRIMARY KEY,
            epic_id TEXT,
            task_num INTEGER,
            note_num INTEGER,
            body TEXT
        );
        """
    )


def _insert_item(
    conn: Any,
    *,
    id_: int,
    status: str,
    spec: str = "",
    technical_plan: str = "",
    test_results: str = "",
    worktree_plan: str = "",
) -> None:
    conn.execute(
        "INSERT INTO items (id, status, spec, technical_plan, test_results,"
        " worktree_plan) VALUES (%s, %s, %s, %s, %s, %s)",
        (id_, status, spec, technical_plan, test_results, worktree_plan),
    )
    conn.commit()


def _insert_epic_task(
    conn: Any, *, epic_id: int, task_num: int, body: str
) -> None:
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, body) VALUES (%s, %s, %s)",
        (epic_id, task_num, body),
    )
    conn.commit()


def _insert_progress_note(
    conn: Any,
    *,
    epic_id: int,
    task_num: int,
    note_num: int,
    body: str,
) -> None:
    conn.execute(
        "INSERT INTO epic_progress_notes (epic_id, task_num, note_num, body)"
        " VALUES (%s, %s, %s, %s)",
        (str(epic_id), task_num, note_num, body),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# items.* fields — terminal vs non-terminal owner status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_item_spec_is_skipped(status: str) -> None:
    conn = _build_db()
    _insert_item(
        conn,
        id_=100,
        status=status,
        spec=f"historical note about {_retired_shell()} usage\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_non_terminal_item_spec_is_flagged() -> None:
    conn = _build_db()
    _insert_item(
        conn,
        id_=101,
        status="refined-idea",
        spec=f"planned cleanup of {_retired_shell()} references\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("items:101:spec:") for h in hits), hits
    assert any(_retired_shell() in h for h in hits), hits


def test_non_terminal_item_other_fields_are_flagged() -> None:
    conn = _build_db()
    _insert_item(
        conn,
        id_=102,
        status="implementing",
        technical_plan=f"plan touches {_retired_shell()}\n",
        test_results=f"ran against {_retired_hook()}\n",
        worktree_plan=f"branch maintains {_retired_shell()} compat\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("items:102:technical_plan:") for h in hits), hits
    assert any(h.startswith("items:102:test_results:") for h in hits), hits
    assert any(h.startswith("items:102:worktree_plan:") for h in hits), hits


# ---------------------------------------------------------------------------
# epic_tasks.body — terminal vs non-terminal owner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_epic_skips_task_body(status: str) -> None:
    conn = _build_db()
    _insert_item(conn, id_=200, status=status)
    _insert_epic_task(
        conn,
        epic_id=200,
        task_num=1,
        body=f"historical step touching {_retired_shell()}\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_non_terminal_epic_flags_task_body() -> None:
    conn = _build_db()
    _insert_item(conn, id_=201, status="implementing")
    _insert_epic_task(
        conn,
        epic_id=201,
        task_num=2,
        body=f"planned step touching {_retired_hook()}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("epic_tasks:201/2:body:") for h in hits), hits
    assert any(_retired_hook() in h for h in hits), hits


# ---------------------------------------------------------------------------
# epic_progress_notes.body — terminal vs non-terminal owner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_epic_skips_progress_note(status: str) -> None:
    conn = _build_db()
    _insert_item(conn, id_=300, status=status)
    _insert_progress_note(
        conn,
        epic_id=300,
        task_num=1,
        note_num=1,
        body=f"historical note about {_retired_shell()}\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_non_terminal_epic_flags_progress_note() -> None:
    conn = _build_db()
    _insert_item(conn, id_=301, status="implementing")
    _insert_progress_note(
        conn,
        epic_id=301,
        task_num=3,
        note_num=2,
        body=f"live progress mentions {_retired_hook()}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("epic_progress_notes:301/3/2:body:") for h in hits), hits


# ---------------------------------------------------------------------------
# Source-label format
# ---------------------------------------------------------------------------


def test_source_labels_identify_table_owner_field() -> None:
    """AC-8: source labels deterministically encode table, owner id(s), and field."""
    conn = _build_db()
    _insert_item(
        conn,
        id_=600,
        status="refined-idea",
        spec=f"touches {_retired_shell()}\n",
    )
    _insert_epic_task(
        conn,
        epic_id=600,
        task_num=4,
        body=f"touches {_retired_shell()}\n",
    )
    _insert_progress_note(
        conn,
        epic_id=600,
        task_num=4,
        note_num=1,
        body=f"touches {_retired_shell()}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("items:600:spec:") for h in hits), hits
    assert any(h.startswith("epic_tasks:600/4:body:") for h in hits), hits
    assert any(h.startswith("epic_progress_notes:600/4/1:body:") for h in hits), hits


# ---------------------------------------------------------------------------
# Negative paths (AC-9: read-only, robust to partial fixtures)
# ---------------------------------------------------------------------------


def test_clean_non_terminal_item_returns_no_hits() -> None:
    conn = _build_db()
    _insert_item(
        conn,
        id_=400,
        status="refined-idea",
        spec="standard spec text with no retired surface names\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_none_connection_returns_empty() -> None:
    assert scan_backlog_fields(None, PATTERNS, LABELS) == []


def test_empty_patterns_returns_empty() -> None:
    conn = _build_db()
    _insert_item(
        conn,
        id_=500,
        status="refined-idea",
        spec=f"touches {_retired_shell()}\n",
    )
    assert scan_backlog_fields(conn, (), {}) == []


def test_missing_epic_tables_do_not_error() -> None:
    """Doctor fixtures sometimes seed only ``items`` — the scanner must
    treat missing ``epic_tasks`` / ``epic_progress_notes`` as a no-op rather
    than an error so it remains compatible with partial schemas."""
    conn = _disposable_pg_db(
        "CREATE TABLE items ("
        "id INTEGER PRIMARY KEY, status TEXT, spec TEXT, technical_plan TEXT,"
        " test_results TEXT, worktree_plan TEXT)"
    )
    _insert_item(
        conn,
        id_=700,
        status="refined-idea",
        spec=f"touches {_retired_shell()}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("items:700:spec:") for h in hits), hits


def test_scanner_does_not_mutate_db() -> None:
    """AC-9: the scanner is read-only — no row count changes after a scan."""
    conn = _build_db()
    _insert_item(
        conn,
        id_=800,
        status="refined-idea",
        spec=f"touches {_retired_shell()}\n",
    )
    _insert_epic_task(
        conn,
        epic_id=800,
        task_num=1,
        body=f"touches {_retired_shell()}\n",
    )
    _insert_progress_note(
        conn,
        epic_id=800,
        task_num=1,
        note_num=1,
        body=f"touches {_retired_shell()}\n",
    )
    pre_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("items", "epic_tasks", "epic_progress_notes")
    }
    scan_backlog_fields(conn, PATTERNS, LABELS)
    post_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("items", "epic_tasks", "epic_progress_notes")
    }
    assert pre_counts == post_counts

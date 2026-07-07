"""Tests for the obsoleting-ticket self-exemption in the backlog scanner.

A retired term whose label embeds ``YOK-N`` (the ticket that retired the
term) must not flag mentions of that term inside ``YOK-N``'s OWN backlog
fields — the spec/plan/task-body/progress-note content explaining what is
being retired. Without this exemption, every rename ticket creates a
structural catch-22: the very ticket retiring a symbol can never PASS
``HC-obsoleted-terms`` because it must spell the symbol out in its own
description.

Lives in a sibling file so the parent ``test_doctor_hc_obsoleted_terms_backlog.py``
stays at its 349-line cap.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_obsoleted_terms_backlog import (
    scan_backlog_fields,
)


# Synthetic patterns + labels. ``LABEL_OWNED`` embeds a sample ticket id so the
# exemption applies to mentions inside item 1674's backlog fields. ``LABEL_UNOWNED``
# carries no YOK-N marker, so no exemption applies.
_RETIRED_OWNED = "retired_owned_symbol"
_RETIRED_UNOWNED = "retired_unowned_symbol"

PATTERNS: tuple[str, ...] = (
    r"\b" + _RETIRED_OWNED + r"\b",
    r"\b" + _RETIRED_UNOWNED + r"\b",
)
LABELS: dict[str, str] = {
    PATTERNS[0]: f"{_RETIRED_OWNED} (YOK-1674 retired — renamed to new_name)",
    PATTERNS[1]: f"{_RETIRED_UNOWNED} (retired pre-tracking; no YOK-N owner)",
}


def _build_db() -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        conn,
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
        """,
    )
    return pg_testdb.drop_database_on_close(conn, name)


def _insert_item(
    conn: Any, *, id_: int, status: str, spec: str = "",
    technical_plan: str = "",
) -> None:
    conn.execute(
        "INSERT INTO items (id, status, spec, technical_plan, test_results,"
        " worktree_plan) VALUES (%s, %s, %s, %s, %s, %s)",
        (id_, status, spec, technical_plan, "", ""),
    )
    conn.commit()


def _insert_epic_task(
    conn: Any, *, epic_id: int, task_num: int, body: str,
) -> None:
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, body) VALUES (%s, %s, %s)",
        (epic_id, task_num, body),
    )
    conn.commit()


def _insert_progress_note(
    conn: Any, *, epic_id: int, task_num: int, note_num: int,
    body: str,
) -> None:
    conn.execute(
        "INSERT INTO epic_progress_notes (epic_id, task_num, note_num, body)"
        " VALUES (%s, %s, %s, %s)",
        (str(epic_id), task_num, note_num, body),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# items.* fields — obsoleting ticket exempts itself
# ---------------------------------------------------------------------------


def test_obsoleting_ticket_spec_is_exempt() -> None:
    """YOK-1674's spec mentioning ``retired_owned_symbol`` is the
    meta-content of the retirement — not live residue."""
    conn = _build_db()
    _insert_item(
        conn, id_=1674, status="implementing",
        spec=f"this ticket retires {_RETIRED_OWNED}\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_other_ticket_spec_still_flagged_for_same_term() -> None:
    """A different item touching the retired term is still flagged."""
    conn = _build_db()
    _insert_item(
        conn, id_=999, status="implementing",
        spec=f"old code still references {_RETIRED_OWNED}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("items:999:spec:") for h in hits), hits


def test_obsoleting_ticket_still_flags_unowned_term() -> None:
    """The exemption is per-label: mentions of OTHER retired terms (whose
    labels carry no YOK-N marker) in the obsoleting ticket's own spec
    remain flagged."""
    conn = _build_db()
    _insert_item(
        conn, id_=1674, status="implementing",
        spec=f"retires {_RETIRED_OWNED} but also touches {_RETIRED_UNOWNED}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(_RETIRED_UNOWNED in h for h in hits), hits
    assert not any(
        h.startswith("items:1674:spec:") and _RETIRED_OWNED in h
        and _RETIRED_UNOWNED not in h
        for h in hits
    ), hits


def test_obsoleting_ticket_technical_plan_is_exempt() -> None:
    conn = _build_db()
    _insert_item(
        conn, id_=1674, status="implementing",
        technical_plan=f"## Plan\nTask N: rename {_RETIRED_OWNED} -> new_name\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


# ---------------------------------------------------------------------------
# epic_tasks.body — owning epic id keys the exemption
# ---------------------------------------------------------------------------


def test_obsoleting_ticket_epic_task_body_is_exempt() -> None:
    """When the obsoleting ticket is an epic, its epic_tasks.body content
    is exempt (the task body describes what to retire)."""
    conn = _build_db()
    _insert_item(conn, id_=1674, status="implementing")
    _insert_epic_task(
        conn, epic_id=1674, task_num=9,
        body=f"# Task 9\nScrub references to {_RETIRED_OWNED}\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_other_epic_task_body_still_flagged() -> None:
    conn = _build_db()
    _insert_item(conn, id_=2222, status="implementing")
    _insert_epic_task(
        conn, epic_id=2222, task_num=1,
        body=f"# Task 1\nMissed cleanup — still uses {_RETIRED_OWNED}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(h.startswith("epic_tasks:2222/1:body:") for h in hits), hits


# ---------------------------------------------------------------------------
# epic_progress_notes.body — owning epic id keys the exemption
# ---------------------------------------------------------------------------


def test_obsoleting_ticket_progress_note_is_exempt() -> None:
    """The obsoleting epic's progress notes routinely name the term in
    receipts and submission-check evidence; those are not live residue."""
    conn = _build_db()
    _insert_item(conn, id_=1674, status="implementing")
    _insert_progress_note(
        conn, epic_id=1674, task_num=9, note_num=1,
        body=f"## Progress note\nRenamed {_RETIRED_OWNED} across all files\n",
    )
    assert scan_backlog_fields(conn, PATTERNS, LABELS) == []


def test_other_epic_progress_note_still_flagged() -> None:
    conn = _build_db()
    _insert_item(conn, id_=3333, status="implementing")
    _insert_progress_note(
        conn, epic_id=3333, task_num=1, note_num=1,
        body=f"Forgot to clean up {_RETIRED_OWNED}\n",
    )
    hits = scan_backlog_fields(conn, PATTERNS, LABELS)
    assert any(
        h.startswith("epic_progress_notes:3333/1/1:body:") for h in hits
    ), hits


# ---------------------------------------------------------------------------
# Label parsing edge cases
# ---------------------------------------------------------------------------


def test_label_without_yok_n_has_no_exemption() -> None:
    """Patterns whose label carries no YOK-N marker flag the obsoleting
    candidate too — no implicit exemption."""
    patterns = (r"\b" + _RETIRED_UNOWNED + r"\b",)
    labels = {patterns[0]: LABELS[PATTERNS[1]]}
    conn = _build_db()
    _insert_item(
        conn, id_=1674, status="implementing",
        spec=f"touches {_RETIRED_UNOWNED}\n",
    )
    hits = scan_backlog_fields(conn, patterns, labels)
    assert any(h.startswith("items:1674:spec:") for h in hits), hits


def test_label_with_multiple_yok_n_uses_first() -> None:
    """The first YOK-N in the label wins. Labels with a back-reference
    cluster (``retired ... YOK-9999 follow-up``) are exempted
    for the first ticket only — pragmatic enough for the live shape."""
    patterns = (r"\b" + _RETIRED_OWNED + r"\b",)
    labels = {
        patterns[0]: (
            f"{_RETIRED_OWNED} (YOK-1674 retired; follow-up tracked under YOK-9999)"
        ),
    }
    conn = _build_db()
    _insert_item(
        conn, id_=1674, status="implementing",
        spec=f"retires {_RETIRED_OWNED}\n",
    )
    _insert_item(
        conn, id_=9999, status="implementing",
        spec=f"follow-up still mentions {_RETIRED_OWNED}\n",
    )
    hits = scan_backlog_fields(conn, patterns, labels)
    assert not any(h.startswith("items:1674:") for h in hits), hits
    assert any(h.startswith("items:9999:") for h in hits), hits

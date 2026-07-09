"""HC-obsoleted-terms backlog-field scanner.

Read-only complement to the file-tree scanner in
:mod:`doctor_hc_obsoleted_terms`. Honors the archive-and-historical-fields
preservation policy recorded in
``docs/archive/decisions/historical-obsoleted-hook-refs.md``: structured
backlog fields on items in historical statuses (``done``, ``release``,
``implemented``, ``cancelled``) record what the work touched at authoring
time and stay out of scope. ``done``/``release``/``implemented`` capture
shipped work; ``cancelled`` captures intentionally abandoned work. Both
are historical authoring records, not live residue. The same fields on
non-terminal items (``idea``, ``refining-idea``, ``implementing``, etc.)
remain in scope.

Inspected fields:

- ``items.spec``, ``items.technical_plan``, ``items.test_results``,
  ``items.worktree_plan`` — keyed by the owning item's status.
- ``epic_tasks.body`` — owning item is ``items.id == epic_tasks.epic_id``
  (bare integer).
- ``epic_progress_notes.body`` — same join (the ``epic_id`` column is
  ``TEXT`` and is cast to ``INTEGER`` for the join).

The scanner uses the doctor-provided DB connection for read-only
queries. It never mutates any row and never resolves DB paths directly,
so it does not require a governed DB mutation claim.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
import re
from typing import Any, Mapping, Sequence, Tuple

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"done", "release", "implemented", "cancelled"}
)

_ITEM_FIELDS: tuple[str, ...] = (
    "spec",
    "technical_plan",
    "test_results",
    "worktree_plan",
)

_LINE_PREVIEW_LIMIT = 160

# Obsoleting-ticket self-exemption. When an obsoleted-term label embeds a
# ``YOK-N`` marker naming the retiring ticket, mentions of the term inside
# that ticket's own backlog fields are the meta-content describing the
# retirement, not live residue. Without this exemption every rename ticket
# would create a structural catch-22 — the very ticket retiring a symbol
# could never PASS the HC because it must spell the symbol out in its own
# description. Parsing ``YOK-N`` out of the label lets the scanner skip hits
# whose source item id matches the retiring ticket id.
_LABEL_TICKET_PATTERN = re.compile(r"\bYOK-(\d+)\b")


def _terminal_status_params() -> tuple[str, ...]:
    """Return the terminal statuses in stable order for SQL parameters."""
    return tuple(sorted(TERMINAL_STATUSES))


def _terminal_placeholders() -> str:
    return ",".join(["%s"] * len(TERMINAL_STATUSES))


def _compile(patterns: Sequence[str]) -> list[Tuple[str, re.Pattern[str]]]:
    return [(p, re.compile(p)) for p in patterns]


def _obsoleting_ticket_id(label: str) -> int | None:
    """Extract the YOK-N item id from an obsoleted-term label, if present.

    Labels that embed the retiring ticket id (``"... (YOK-N retired — ...)"``)
    let the scanner key the self-exemption to that item id. Labels without
    a ``YOK-N`` token return ``None`` — no self-exemption applies (those
    terms were retired by an earlier untracked migration or a non-ticket
    cleanup).
    """
    match = _LABEL_TICKET_PATTERN.search(label)
    if match is None:
        return None
    return int(match.group(1))


def _scan_text(
    text: str,
    compiled: Sequence[Tuple[str, re.Pattern[str]]],
    labels: Mapping[str, str],
    source_label: str,
    source_item_id: int | None = None,
) -> list[str]:
    """Return ``<source-label>:<line>: [<retired-label>] <content>`` strings.

    Matches the format of :func:`doctor_hc_obsoleted_terms.scan_repo` so the
    HC report renders file-tree hits and backlog-field hits side-by-side
    without per-source formatting branches.

    ``source_item_id`` enables the obsoleting-ticket self-exemption: when a
    pattern's label names the same YOK-N as the source item, the hit is
    skipped. The exemption applies only to backlog fields (this module's
    scope); the file-tree scanner in ``doctor_hc_obsoleted_terms`` has no
    item id to key on and remains strict.
    """
    if not text:
        return []
    out: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for pattern_src, compiled_pattern in compiled:
            if compiled_pattern.search(line):
                label = labels.get(pattern_src, pattern_src)
                if source_item_id is not None:
                    obsoleting_id = _obsoleting_ticket_id(label)
                    if obsoleting_id == source_item_id:
                        continue
                preview = line.rstrip()[:_LINE_PREVIEW_LIMIT]
                out.append(f"{source_label}:{i}: [{label}] {preview}")
    return out


def _safe_execute(conn: Any, sql: str, params: tuple):
    """Run a read-only query, returning ``None`` if the table is missing.

    Doctor test fixtures sometimes seed only a subset of the live schema;
    a missing ``epic_tasks`` or ``epic_progress_notes`` table is not a
    scanner failure, just a "nothing to scan" signal. The rollback clears
    the aborted-transaction state a failed statement leaves on Postgres so
    later scans on the same connection still run.
    """
    try:
        return conn.execute(sql, params)
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def _scan_items_fields(
    conn: Any,
    compiled: Sequence[Tuple[str, re.Pattern[str]]],
    labels: Mapping[str, str],
) -> list[str]:
    sql = (
        "SELECT id," + ",".join(_ITEM_FIELDS) + " FROM items "
        f"WHERE status NOT IN ({_terminal_placeholders()}) OR status IS NULL"
    )
    cur = _safe_execute(conn, sql, _terminal_status_params())
    if cur is None:
        return []
    hits: list[str] = []
    for row in cur.fetchall():
        item_id = row[0]
        if item_id is None:
            continue
        item_id_int = int(item_id)
        for col_idx, field in enumerate(_ITEM_FIELDS, start=1):
            value = row[col_idx]
            if not value:
                continue
            hits.extend(
                _scan_text(
                    value,
                    compiled,
                    labels,
                    f"items:{item_id_int}:{field}",
                    source_item_id=item_id_int,
                )
            )
    return hits


def _scan_epic_task_bodies(
    conn: Any,
    compiled: Sequence[Tuple[str, re.Pattern[str]]],
    labels: Mapping[str, str],
) -> list[str]:
    sql = (
        "SELECT et.epic_id, et.task_num, et.body "
        "FROM epic_tasks et "
        "JOIN items i ON i.id = et.epic_id "
        f"WHERE i.status NOT IN ({_terminal_placeholders()}) OR i.status IS NULL"
    )
    cur = _safe_execute(conn, sql, _terminal_status_params())
    if cur is None:
        return []
    hits: list[str] = []
    for row in cur.fetchall():
        epic_id, task_num, body = row[0], row[1], row[2]
        if not body or epic_id is None or task_num is None:
            continue
        epic_id_int = int(epic_id)
        hits.extend(
            _scan_text(
                body,
                compiled,
                labels,
                f"epic_tasks:{epic_id_int}/{int(task_num)}:body",
                source_item_id=epic_id_int,
            )
        )
    return hits


def _scan_progress_note_bodies(
    conn: Any,
    compiled: Sequence[Tuple[str, re.Pattern[str]]],
    labels: Mapping[str, str],
) -> list[str]:
    sql = (
        "SELECT epn.epic_id, epn.task_num, epn.note_num, epn.body "
        "FROM epic_progress_notes epn "
        "JOIN items i ON i.id = CAST(epn.epic_id AS INTEGER) "
        f"WHERE i.status NOT IN ({_terminal_placeholders()}) OR i.status IS NULL"
    )
    cur = _safe_execute(conn, sql, _terminal_status_params())
    if cur is None:
        return []
    hits: list[str] = []
    for row in cur.fetchall():
        epic_id, task_num, note_num, body = row[0], row[1], row[2], row[3]
        if not body or epic_id is None or task_num is None or note_num is None:
            continue
        epic_id_int = int(epic_id)
        hits.extend(
            _scan_text(
                body,
                compiled,
                labels,
                f"epic_progress_notes:{epic_id_int}/{int(task_num)}/{int(note_num)}:body",
                source_item_id=epic_id_int,
            )
        )
    return hits


def scan_backlog_fields(
    conn: Any | None,
    patterns: Sequence[str],
    labels: Mapping[str, str],
) -> list[str]:
    """Scan structured backlog fields owned by non-historical items.

    Returns a list of ``<source-label>:<line>: [<retired-label>] <content>``
    strings matching the format of
    :func:`doctor_hc_obsoleted_terms.scan_repo`. Empty list when ``conn`` is
    ``None`` (synthetic test path), when ``patterns`` is empty, or when no
    non-historical item carries an obsoleted-term hit.
    """
    if conn is None or not patterns:
        return []
    compiled = _compile(patterns)
    if not compiled:
        return []
    hits: list[str] = []
    hits.extend(_scan_items_fields(conn, compiled, labels))
    hits.extend(_scan_epic_task_bodies(conn, compiled, labels))
    hits.extend(_scan_progress_note_bodies(conn, compiled, labels))
    return hits

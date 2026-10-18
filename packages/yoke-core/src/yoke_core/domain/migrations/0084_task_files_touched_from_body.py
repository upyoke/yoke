"""Make each task body's ``## Files Touched`` its only file list.

Generated tasks kept their file list twice: the body section the Architect
writes, and ``epic_task_files`` rows every check read. Nothing kept the two
in sync. This entry makes the body carry what the rows said, then drops the
rows and the per-task scope columns:

- a task with rows whose section already parses to exactly those paths is
  left alone;
- any other task with rows gets a canonical section, one ``- verb `path```
  bullet per row (``create``/``modify``/``delete`` when the stored action
  starts with that verb, otherwise ``modify``). Its previous section and
  every row as stored — path and full action text, including rows whose
  path is not a repository path token — are kept under
  :data:`SUPERSEDED_HEADING`, which no reader parses;
- a task declared ``no_files`` gets the explicit no-files line the same way.

Every rewritten task is parsed again before anything is dropped; any
difference aborts the entry with the tasks named.
"""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.file_budget_paths import is_path_token
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.task_files_touched import (
    FILE_ACTIONS,
    FILES_TOUCHED_HEADING,
    STATE_NO_FILES,
    parse_files_touched,
    render_files_touched,
)

#: A build older than this entry reads ``epic_task_files`` and the scope
#: columns on every coverage check, so it cannot serve a converged database.
MINIMUM_SERVING_VERSION = NEXT_RELEASE

TABLE = "epic_task_files"
TASKS = "epic_tasks"
RETIRED_COLUMNS = ("scope_state", "scope_finalized_at")
SUPERSEDED_HEADING = "## Superseded Files Touched notes"
_HEADING = re.compile(rf"^{re.escape(FILES_TOUCHED_HEADING)}\b")


class TaskFilesRewriteMismatch(RuntimeError):
    """A rewritten body does not parse back to its task's rows."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _verb(action: str) -> str:
    words = (action or "").strip().split()
    first = words[0].strip(".,:;()—-").lower() if words else ""
    return first if first in FILE_ACTIONS else "modify"


def _split_section(body: str) -> tuple[str, str, str]:
    """Split ``body`` into text before, the Files Touched section, and after."""
    lines = body.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if _HEADING.match(line.strip())),
        None,
    )
    if start is None:
        return body, "", ""
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip().startswith("## ")
        ),
        len(lines),
    )
    return "".join(lines[:start]), "".join(lines[start:end]), "".join(lines[end:])


def _rewrite(
    body: str, entries: list[tuple[str, str]], rows: list[tuple[str, str]]
) -> str:
    before, section, after = _split_section(body)
    notes = []
    if section.strip():
        old = section.strip().splitlines()[1:]
        notes.append("Previous section text:\n\n" + "\n".join(old).strip())
    if rows:
        notes.append(
            "File rows as stored:\n\n"
            + "\n".join(
                f"- `{path}`" + (f" — {action}" if action else "")
                for path, action in rows
            )
        )
    superseded = (
        f"{SUPERSEDED_HEADING}\n\n" + "\n\n".join(notes) + "\n" if notes else ""
    )
    head = before.rstrip()
    parts = [head] if head else []
    parts.append(render_files_touched(entries).rstrip())
    if superseded:
        parts.append(superseded.rstrip())
    if after.strip():
        parts.append(after.strip())
    return "\n\n".join(parts) + "\n"


def _tasks(conn: Any) -> list[tuple[int, int, str, str]]:
    state = "scope_state" if _column_exists(conn, TASKS, "scope_state") else "''"
    rows = conn.execute(
        f"SELECT epic_id, task_num, COALESCE(body, ''), COALESCE({state}, '') "
        f"FROM {TASKS} ORDER BY epic_id, task_num"
    ).fetchall()
    return [(int(r[0]), int(r[1]), str(r[2]), str(r[3])) for r in rows]


def _file_rows(conn: Any) -> dict[tuple[int, int], list[tuple[str, str]]]:
    if not _table_exists(conn, TABLE):
        return {}
    result: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for row in conn.execute(
        f"SELECT epic_id, task_num, file_path, COALESCE(action, '') FROM {TABLE} "
        "WHERE TRIM(COALESCE(file_path, '')) <> '' ORDER BY epic_id, task_num, id"
    ).fetchall():
        key = (int(row[0]), int(row[1]))
        result.setdefault(key, []).append((str(row[2]).strip(), str(row[3])))
    return result


def _expected(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(_verb(action), path) for path, action in rows if is_path_token(path)]


def _matches(body: str, expected: list[tuple[str, str]]) -> bool:
    parsed = parse_files_touched(body)
    if not expected:
        return parsed.state == STATE_NO_FILES
    return set(parsed.paths) == {path for _verb_, path in expected}


def apply(conn: Any) -> None:
    """Carry every task's rows into its body, verify, then drop the rows."""
    if not _table_exists(conn, TASKS):
        return
    marker = _p(conn)
    file_rows = _file_rows(conn)
    checked: list[tuple[int, int, list[tuple[str, str]]]] = []
    for epic_id, task_num, body, state in _tasks(conn):
        rows = file_rows.get((epic_id, task_num), [])
        if not rows and state != STATE_NO_FILES:
            continue
        expected = _expected(rows)
        checked.append((epic_id, task_num, expected))
        if _matches(body, expected):
            continue
        conn.execute(
            f"UPDATE {TASKS} SET body = {marker} "
            f"WHERE epic_id = {marker} AND task_num = {marker}",
            (_rewrite(body, expected, rows), epic_id, task_num),
        )
    _verify(conn, checked)
    if _table_exists(conn, TABLE):
        conn.execute(f'DROP TABLE "{TABLE}"')
    for column in RETIRED_COLUMNS:
        if _column_exists(conn, TASKS, column):
            conn.execute(f'ALTER TABLE "{TASKS}" DROP COLUMN "{column}"')


def _verify(conn: Any, checked: list[tuple[int, int, list[tuple[str, str]]]]) -> None:
    marker = _p(conn)
    mismatched = []
    for epic_id, task_num, expected in checked:
        row = conn.execute(
            f"SELECT COALESCE(body, '') FROM {TASKS} "
            f"WHERE epic_id = {marker} AND task_num = {marker}",
            (epic_id, task_num),
        ).fetchone()
        if not _matches(str(row[0]), expected):
            mismatched.append(f"item id {epic_id} task {task_num}")
    if mismatched:
        raise TaskFilesRewriteMismatch(
            "task_files_touched_rewrite_mismatch: rewritten Files Touched "
            f"sections do not parse back to their rows for {len(mismatched)} "
            f"task(s): {', '.join(mismatched[:20])}; nothing was dropped. "
            "Recovery: fix the parser or the rewrite in this entry and rerun "
            "the converge; the rows are intact."
        )


def invariants(conn: Any) -> None:
    """Prove the rows and the per-task scope columns are gone."""
    assert not _table_exists(conn, TABLE), f"{TABLE} must be absent after convergence"
    if _table_exists(conn, TASKS):
        for column in RETIRED_COLUMNS:
            assert not _column_exists(conn, TASKS, column), (
                f"{TASKS}.{column} must be absent after convergence"
            )


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMNS",
    "SUPERSEDED_HEADING",
    "TABLE",
    "TaskFilesRewriteMismatch",
    "apply",
    "invariants",
]

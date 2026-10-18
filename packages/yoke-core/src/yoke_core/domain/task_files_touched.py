"""A generated task's file list, read from its body's ``## Files Touched``.

The task body is the only per-task file list. Each bullet names one
backticked repository path, written ``- create|modify|delete `path```; the
path language is the File Budget's (:mod:`file_budget_paths`). A section
whose only content is ``None — no repository files`` declares, explicitly,
that the task touches nothing. Every other shape is reported rather than
guessed at, so a check reading the list can fail closed:

- ``missing``: the body has no ``## Files Touched`` section;
- ``unparseable``: the section names no path and is not the no-files line,
  or names paths and the no-files line together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.file_budget_paths import (
    extract_section,
    extract_section_paths,
)

FILES_TOUCHED_SECTION = "Files Touched"
FILES_TOUCHED_HEADING = f"## {FILES_TOUCHED_SECTION}"
NO_FILES_LINE = "None — no repository files"
FILE_ACTIONS = ("create", "modify", "delete")

STATE_PATHS = "paths"
STATE_NO_FILES = "no_files"
STATE_MISSING = "missing"
STATE_UNPARSEABLE = "unparseable"

_NO_FILES = re.compile(
    r"^\s*(?:-\s*)?none\s*[—–-]+\s*no repository files\.?\s*$",
    re.IGNORECASE,
)

#: The authoring recipe every refusal names, so a reader can fix the body.
FILES_TOUCHED_RECIPE = (
    f"write the task body's `{FILES_TOUCHED_HEADING}` section as one bullet "
    "per path (`- modify `path/to/file.py``, verbs create|modify|delete), or "
    f"as the single line `{NO_FILES_LINE}`, with "
    "`yoke workflow-item epic-task body-replace`"
)


@dataclass(frozen=True)
class TaskFiles:
    """What one task body declares about the repository files it touches."""

    state: str
    paths: tuple[str, ...] = ()

    @property
    def declared(self) -> bool:
        return self.state in (STATE_PATHS, STATE_NO_FILES)

    def problem(self) -> str:
        """Describe an undeclared list, or return ``""`` when it is declared."""
        if self.state == STATE_MISSING:
            return f"has no {FILES_TOUCHED_HEADING} section"
        if self.state == STATE_UNPARSEABLE:
            return (
                f"has a {FILES_TOUCHED_HEADING} section that names no path "
                f"and is not `{NO_FILES_LINE}`"
            )
        return ""


def parse_files_touched(body: str | None) -> TaskFiles:
    """Read one task body's declared file list."""
    text = body or ""
    section = extract_section(text, FILES_TOUCHED_HEADING)
    if section is None:
        return TaskFiles(STATE_MISSING)
    paths = tuple(extract_section_paths(text, FILES_TOUCHED_HEADING))
    lines = [line for line in section.splitlines() if line.strip()]
    no_files = any(_NO_FILES.match(line) for line in lines)
    if paths and not no_files:
        return TaskFiles(STATE_PATHS, paths)
    if no_files and not paths and len(lines) == 1:
        return TaskFiles(STATE_NO_FILES)
    return TaskFiles(STATE_UNPARSEABLE)


def render_files_touched(entries: Iterable[tuple[str, str]]) -> str:
    """Render the canonical section from ``(action, path)`` pairs."""
    lines = [f"- {action} `{path}`" for action, path in entries]
    body = "\n".join(lines) if lines else NO_FILES_LINE
    return f"{FILES_TOUCHED_HEADING}\n\n{body}\n"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def item_task_files(conn: Any, item_id: int) -> dict[int, TaskFiles]:
    """Read every generated task's declared file list for one item."""
    rows = conn.execute(
        "SELECT task_num, COALESCE(body, '') AS body FROM epic_tasks "
        f"WHERE epic_id = {_p(conn)} ORDER BY task_num",
        (int(item_id),),
    ).fetchall()
    result: dict[int, TaskFiles] = {}
    for row in rows:
        task_num = row["task_num"] if hasattr(row, "keys") else row[0]
        body = row["body"] if hasattr(row, "keys") else row[1]
        result[int(task_num)] = parse_files_touched(str(body))
    return result


__all__ = [
    "FILES_TOUCHED_HEADING",
    "FILES_TOUCHED_RECIPE",
    "FILES_TOUCHED_SECTION",
    "FILE_ACTIONS",
    "NO_FILES_LINE",
    "STATE_MISSING",
    "STATE_NO_FILES",
    "STATE_PATHS",
    "STATE_UNPARSEABLE",
    "TaskFiles",
    "item_task_files",
    "parse_files_touched",
    "render_files_touched",
]

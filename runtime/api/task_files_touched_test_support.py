"""Write a generated task's ``## Files Touched`` section in test fixtures."""

from __future__ import annotations

import re
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.task_files_touched import render_files_touched

_SECTION = re.compile(r"^## Files Touched\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def files_touched_body(paths: Iterable[str], body: str = "") -> str:
    """Return ``body`` with its Files Touched section declaring ``paths``."""
    section = render_files_touched(("modify", str(path)) for path in paths)
    rest = _SECTION.sub("", body or "").rstrip()
    return f"{rest}\n\n{section}" if rest else section


def declare_task_files(
    conn: Any,
    epic_id: int | str,
    task_num: int,
    paths: Iterable[str],
) -> None:
    """Rewrite one task body so its Files Touched lists ``paths``.

    An empty ``paths`` declares ``None — no repository files``.
    """
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT COALESCE(body, '') FROM epic_tasks "
        f"WHERE epic_id={marker} AND task_num={marker}",
        (int(epic_id), int(task_num)),
    ).fetchone()
    current = "" if row is None else str(row[0] if not hasattr(row, "keys") else row[0])
    conn.execute(
        f"UPDATE epic_tasks SET body={marker} "
        f"WHERE epic_id={marker} AND task_num={marker}",
        (files_touched_body(paths, current), int(epic_id), int(task_num)),
    )


__all__ = ["declare_task_files", "files_touched_body"]

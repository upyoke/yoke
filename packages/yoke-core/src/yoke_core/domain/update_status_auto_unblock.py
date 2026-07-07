"""Dependency-aware auto-unblock for epic tasks.

When a task reaches terminal success, scan blocked sibling tasks in the same
epic and unblock those whose declared dependencies are now satisfied. The
recursive transition into ``implementing`` is delegated back to
``update_task_status`` (deferred-imported to avoid the circular dependency
with the front-door module).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional, TextIO

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def auto_unblock(
    conn: Any,
    epic_id: str,
    task_num: str,
    new_status: str,
    *,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> None:
    """Unblock dependent tasks when a task reaches terminal success."""
    stdout = stdout or sys.stdout

    if new_status not in TASK_TERMINAL_SUCCESS:
        return

    p = _p(conn)
    rows = query_rows(
        conn,
        f"""SELECT task_num, title, dependencies, status
           FROM epic_tasks WHERE epic_id={p}""",
        (str(epic_id),),
    )

    for row in rows:
        r_status = row["status"]
        r_num = str(row["task_num"])
        r_deps = row["dependencies"] or ""

        if r_status != "blocked":
            continue
        if r_num == str(task_num):
            continue
        if not r_deps:
            continue

        # Parse dependencies: "001,002" or "001, 002" etc.
        clean_deps = r_deps.replace("[", "").replace("]", "").replace('"', "").replace("#", "")
        dep_list = [d.strip() for d in clean_deps.split(",") if d.strip()]

        all_met = True
        for dep in dep_list:
            dep_row = query_one(
                conn,
                f"SELECT status FROM epic_tasks WHERE epic_id={p} AND task_num={p}",
                (str(epic_id), dep),
            )
            if dep_row is None:
                all_met = False
                break
            if dep_row["status"] not in TASK_TERMINAL_SUCCESS:
                all_met = False
                break

        if all_met:
            print(f"Auto-unblocking task {r_num} — all dependencies met", file=stdout)
            # Recursive call with system-owned bypass; deferred import breaks
            # the import cycle with the front-door module.
            from yoke_core.domain import update_status as _us

            bypass = f"auto-unblock:epic-{epic_id}-task-{task_num}"
            old_bypass = os.environ.get("YOKE_CLAIM_BYPASS")
            os.environ["YOKE_CLAIM_BYPASS"] = bypass
            try:
                # Land at `planned` so conduct's S6c enumeration treats this as
                # a newly dispatchable head and authors the canonical
                # `planned → implementing` transition with the matching
                # "Dispatched by conduct" note when it picks the task up.
                _us.update_task_status(
                    conn, epic_id, r_num, "planned",
                    note=f"Auto-unblocked: dependency {task_num} completed",
                    stdout=stdout,
                    stderr=stderr,
                )
            finally:
                if old_bypass is not None:
                    os.environ["YOKE_CLAIM_BYPASS"] = old_bypass
                else:
                    os.environ.pop("YOKE_CLAIM_BYPASS", None)

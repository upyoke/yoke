"""Query and display helpers for the merge-readiness audit report.

Split out of :mod:`yoke_core.engines.merge_audit_report` so the renderer
stays under the authored-file line limit. Holds the SQL placeholder and
epic-worktree query builders, the lazy accessor for the parent
:mod:`merge_audit` git helpers, and the guarded public item-ref resolver
the report's display lines call.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    render_item_ref,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# One row per distinct worktree branch for an epic, ordered by the earliest
# task in each worktree. GROUP BY worktree already collapses duplicates, so no
# DISTINCT is needed — and omitting it keeps the ORDER BY MIN(task_num)
# aggregate portable (Postgres rejects ORDER BY expressions absent from the
# SELECT list under SELECT DISTINCT).
def _epic_worktrees_sql(conn) -> str:
    p = _p(conn)
    return (
        "SELECT iw.branch AS worktree FROM epic_tasks t "
        "JOIN item_worktrees iw ON iw.id=t.item_worktree_id "
        f"WHERE t.epic_id = {p} AND iw.state = 'active' "
        "GROUP BY iw.branch ORDER BY MIN(t.task_num)"
    )


def _parent():
    from yoke_core.engines import merge_audit as _ma
    return _ma


def _display_item_ref(conn: Optional[Any], item_id: int) -> str:
    """Public item ref for a merge-audit report display line.

    The report runs every read on one shared connection, and some fixtures
    build a minimal ``items`` schema without the ``projects`` join that
    :func:`render_item_ref` needs. On Postgres a failed lookup aborts the
    surrounding transaction, so roll it back and fall back to the
    default-prefix ref rather than poisoning the rest of the report.
    """
    if conn is not None:
        try:
            return render_item_ref(conn, int(item_id))
        except Exception:  # noqa: BLE001 - a report line must never raise.
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 - best-effort transaction reset.
                pass
    return f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{int(item_id)}"

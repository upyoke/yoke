"""Shared dependency gate with satisfaction evaluation.

Queries ``item_dependencies`` for blocking entries where the given item is
the dependent, evaluates each blocker's satisfaction condition, and
reports unsatisfied blockers. Exits 0 when clear, 1 when blocked.

Public adapter: ``yoke advance preflight hard-blocks PREFIX-N``.
The registered handler owns database evaluation for both transports.

Output format (when blocked, one line per unresolved blocker)::

    BLOCKED|YOK-N|idea|Dependency title|activation|status:done|evaluation reason
    BLOCKED|YOK-M|done|Deploy API|closure|fact:deployed:prod|evaluation reason
"""

from __future__ import annotations

import sys
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain import db_helpers
from yoke_core.domain.dependency_satisfaction import evaluate_persisted_satisfaction
from yoke_core.domain.dependency_workflow_context import (
    workflow_from_joined_values,
)
from yoke_core.domain.item_ref_columns import render_column_item_ref
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)


def _query_blockers(
    conn,
    item_id: int,
    gate_filter: Optional[str] = None,
) -> List[Tuple[str, str, str, Any]]:
    """Return ``[(blocking_item, gate_point, satisfaction, created_at), ...]``.

    ``blocking_item`` in the result is the public PREFIX-N display token.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if gate_filter:
        rows = db_helpers.query_rows(
            conn,
            "SELECT blocking_item_id, gate_point, satisfaction, created_at "
            f"FROM item_dependencies WHERE dependent_item_id = {p} "
            f"AND gate_point = {p} ORDER BY blocking_item_id",
            (item_id, gate_filter),
        )
    else:
        rows = db_helpers.query_rows(
            conn,
            "SELECT blocking_item_id, gate_point, satisfaction, created_at "
            f"FROM item_dependencies WHERE dependent_item_id = {p} "
            "ORDER BY blocking_item_id",
            (item_id,),
        )
    return [
        (
            render_column_item_ref(conn, row["blocking_item_id"]),
            row["gate_point"],
            row["satisfaction"],
            row["created_at"],
        )
        for row in rows
    ]


def _query_item(conn, item_id: int) -> Optional[dict]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = db_helpers.query_one(
        conn,
        "SELECT i.status, i.title, "
        f"{primary_item_worktree_branch_sql('i.id')} AS lane_branch, "
        "p.slug AS project, i.merged_at, "
        "i.workflow_id, i.workflow_version_id, wv.version, "
        "wv.definition_json, wv.definition_digest "
        "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
        "LEFT JOIN workflow_versions wv ON wv.id = i.workflow_version_id "
        f"WHERE i.id = {p}",
        (item_id,),
    )
    if row is None:
        return None
    return {
        "id": int(item_id),
        "status": row["status"],
        "title": row["title"],
        "lane_branch": row["lane_branch"],
        "project": row["project"],
        "merged_at": row["merged_at"],
        "workflow": workflow_from_joined_values(
            row["workflow_id"],
            row["workflow_version_id"],
            row["version"],
            row["definition_json"],
            row["definition_digest"],
        ),
    }


def _evaluate_item_satisfaction(satisfaction: str, item: dict, conn, created_at=None):
    status = item.get("status") or ""
    merged = True if item.get("merged_at") else None
    return evaluate_persisted_satisfaction(
        conn,
        blocking_item_id=item.get("id"),
        satisfaction=satisfaction,
        blocking_status=status,
        blocking_worktree=item.get("lane_branch"),
        blocking_merged=merged,
        blocking_merged_at=item.get("merged_at"),
        dependency_created_at=created_at,
        workflow=item.get("workflow"),
    )


def _is_satisfied(satisfaction: str, item: dict, conn) -> bool:
    return _evaluate_item_satisfaction(satisfaction, item, conn).satisfied


def evaluate_blockers(
    item_id: int,
    gate_filter: Optional[str] = None,
    conn: Optional[Any] = None,
) -> List[str]:
    """Return a list of ``BLOCKED|...`` lines for unsatisfied blockers.

    Uses a single DB connection for the entire evaluation (blockers query
    + per-blocker item lookups + optional project lookups) to avoid the
    N+1 connection-open pattern from the original shell port. A caller
    already inside a transaction — the status-write gate — passes its own
    connection so the evaluation reads the same uncommitted state the
    transition is about to commit.
    """
    if conn is not None:
        return _blocker_lines(conn, item_id, gate_filter)
    with db_helpers.connect() as owned:
        return _blocker_lines(owned, item_id, gate_filter)


def _blocker_lines(
    conn: Any,
    item_id: int,
    gate_filter: Optional[str],
) -> List[str]:
    """Evaluate every blocker on one open connection."""
    output: list[str] = []
    blockers = _query_blockers(conn, item_id, gate_filter=gate_filter)
    if not blockers:
        return output

    from yoke_core.domain.project_identity import (
        render_item_ref,
        unresolved_item_ref,
    )
    from yoke_core.domain.yok_n_parser import parse_item_id_or_none

    for blocking_item, gate_point, satisfaction, created_at in blockers:
        dep_num = parse_item_id_or_none(blocking_item, conn=conn)
        # Fail safe: a blocker ref that does not resolve to a live
        # item still reports as missing rather than silently
        # unblocking the dependent.
        dep_item = None if dep_num is None else _query_item(conn, dep_num)
        if dep_item is None:
            # The stored token is an internal id, which names nothing to a
            # reader; a blocker that resolves to no item says so instead.
            output.append(
                "BLOCKED|%s|missing|<unknown>|%s|%s"
                % (
                    unresolved_item_ref(),
                    gate_point,
                    satisfaction,
                )
            )
            continue
        verdict = _evaluate_item_satisfaction(satisfaction, dep_item, conn, created_at)
        if verdict.satisfied:
            continue
        output.append(
            "BLOCKED|%s|%s|%s|%s|%s|%s"
            % (
                render_item_ref(conn, dep_num),
                dep_item.get("status") or "",
                dep_item.get("title") or "",
                gate_point,
                satisfaction,
                verdict.reason,
            )
        )
    return output


if __name__ == "__main__":
    print(
        "direct_database_entrypoint_retired: use yoke advance preflight "
        "hard-blocks PREFIX-N on your selected connection.",
        file=sys.stderr,
    )
    sys.exit(2)

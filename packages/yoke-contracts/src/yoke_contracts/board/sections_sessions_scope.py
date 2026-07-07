"""Project-scope queries for BOARD.md session rendering."""

from __future__ import annotations

from typing import Any, List, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import (
    scope_project_id,
    visible_project_ids,
)


def session_rows(
    db: BoardDBLike,
    *,
    scope: str,
    active_only: bool,
) -> List[Tuple]:
    """Return active or closed harness-session rows for a board scope."""
    ended_filter = "hs.ended_at IS NULL" if active_only else "hs.ended_at IS NOT NULL"
    order_col = "hs.offered_at" if active_only else "hs.ended_at"
    limit = "" if active_only else "LIMIT 3"
    scope_sql, params = _scope_filter(db, scope, active_only=active_only)
    ended_col = "" if active_only else ", hs.ended_at"
    return db.query_quiet(
        f"""
        SELECT hs.session_id, hs.executor, hs.executor_display_name, hs.model,
               hs.mode, hs.execution_lane, hs.offered_at, hs.last_heartbeat,
               hs.workspace, hs.project_id
               {ended_col}
        FROM harness_sessions hs
        WHERE {ended_filter}
        {scope_sql}
        ORDER BY {order_col} DESC
        {limit}
        """,
        params,
    )


ProjectRow = Tuple[int, str, str]


def session_project_label(
    db: BoardDBLike,
    project_id: Any,
) -> str:
    """Render the project label for a session's stamped project id."""
    try:
        normalized_project_id = int(project_id)
    except (TypeError, ValueError):
        return "—"
    project = _project_for_id(db, normalized_project_id)
    return _format_project_label(project) if project else "—"


def _scope_filter(
    db: BoardDBLike,
    scope: str,
    *,
    active_only: bool,
) -> tuple[str, tuple[Any, ...]]:
    if not scope or scope == "all":
        ids = visible_project_ids()
        if ids is not None:
            return _multi_project_scope_filter(ids, active_only=active_only)
        return "", ()
    project_id = scope_project_id(db, scope)
    claim_sql, claim_params = _claim_scope_filter(project_id, active_only=active_only)
    return (
        f"""
        AND (
            hs.project_id = %s
            OR hs.session_id IN ({claim_sql})
        )
        """,
        (project_id, *claim_params),
    )


def _claim_scope_filter(
    project_id: int,
    *,
    active_only: bool,
) -> tuple[str, tuple[Any, ...]]:
    wc_terminal = "AND wc.released_at IS NULL" if active_only else ""
    pc_terminal = (
        "AND pc.released_at IS NULL AND pc.cancelled_at IS NULL"
        if active_only else ""
    )
    lease_terminal = "AND cl.released_at IS NULL" if active_only else ""
    return (
        f"""
            SELECT wc.session_id
            FROM work_claims wc
            JOIN items wi ON wi.id = wc.item_id
            WHERE wi.project_id = %s {wc_terminal}
            UNION
            SELECT pc.session_id
            FROM path_claims pc
            JOIN items pi ON pi.id = pc.item_id
            WHERE pi.project_id = %s AND pc.session_id IS NOT NULL {pc_terminal}
            UNION
            SELECT cl.session_id
            FROM coordination_leases cl
            WHERE cl.project_id = %s {lease_terminal}
        """,
        (project_id, project_id, project_id),
    )


def _multi_project_scope_filter(
    project_ids: tuple[int, ...],
    *,
    active_only: bool,
) -> tuple[str, tuple[Any, ...]]:
    if not project_ids:
        return "AND 1=0", ()
    claim_sql, claim_params = _claim_scope_filter_for_projects(
        project_ids, active_only=active_only,
    )
    markers = ", ".join("%s" for _ in project_ids)
    return (
        f"""
        AND (
            hs.project_id IN ({markers})
            OR hs.session_id IN ({claim_sql})
        )
        """,
        (*project_ids, *claim_params),
    )


def _claim_scope_filter_for_projects(
    project_ids: tuple[int, ...],
    *,
    active_only: bool,
) -> tuple[str, tuple[Any, ...]]:
    markers = ", ".join("%s" for _ in project_ids)
    wc_terminal = "AND wc.released_at IS NULL" if active_only else ""
    pc_terminal = (
        "AND pc.released_at IS NULL AND pc.cancelled_at IS NULL"
        if active_only else ""
    )
    lease_terminal = "AND cl.released_at IS NULL" if active_only else ""
    return (
        f"""
            SELECT wc.session_id
            FROM work_claims wc
            JOIN items wi ON wi.id = wc.item_id
            WHERE wi.project_id IN ({markers}) {wc_terminal}
            UNION
            SELECT pc.session_id
            FROM path_claims pc
            JOIN items pi ON pi.id = pc.item_id
            WHERE pi.project_id IN ({markers}) AND pc.session_id IS NOT NULL {pc_terminal}
            UNION
            SELECT cl.session_id
            FROM coordination_leases cl
            WHERE cl.project_id IN ({markers}) {lease_terminal}
        """,
        (*project_ids, *project_ids, *project_ids),
    )


def _project_for_id(
    db: BoardDBLike,
    project_id: int,
) -> ProjectRow | None:
    rows = db.query_quiet(
        "SELECT id, slug, COALESCE(emoji, '') FROM projects WHERE id = %s",
        (project_id,),
    )
    if rows:
        return _coerce_project_row(rows[0])
    rows = db.query_quiet(
        "SELECT id, slug FROM projects WHERE id = %s",
        (project_id,),
    )
    if not rows:
        return None
    return _coerce_project_row((rows[0][0], rows[0][1], ""))


def _coerce_project_row(row: Tuple) -> ProjectRow:
    return (
        int(row[0]),
        str(row[1] or ""),
        str(row[2] or ""),
    )


def _format_project_label(project: ProjectRow) -> str:
    slug = project[1] or f"project-{project[0]}"
    emoji = project[2].strip()
    return f"{emoji} {slug}" if emoji else slug

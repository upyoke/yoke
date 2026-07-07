"""Board projection route sub-router.

Owns ``GET /board`` — returns the project board state grouped by status
column, including computed stats and active-run signals.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import Query
from fastapi.routing import APIRouter

from yoke_core.domain import board, db_backend, runs
from yoke_core.domain.project_identity import resolve_project

# Module-level import so test patches against ``yoke_core.api.main.*`` take effect.
import yoke_core.api.main as _main

router = APIRouter()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@router.get("/board", response_model=_main.BoardResponse)
def get_board(
    project: Optional[str] = Query("yoke", description="Project to show board for"),
) -> _main.BoardResponse:
    """Return board state: items grouped by status for a project."""
    conn = _main.get_db_readonly()
    try:
        p = _p(conn)
        ident = resolve_project(conn, project, required=False)
        if ident is None:
            return _main.BoardResponse(
                project=project or "",
                columns={col_name: [] for col_name in board.BOARD_COLUMNS},
                stats=_main.BoardStats(
                    total=0,
                    done=0,
                    active=0,
                    remaining=0,
                ),
            )
        project_id = ident.id
        active_run_exists = runs.sql_active_run_exists_for_item("i.id")
        rows = conn.execute(
            f"""SELECT i.*, {active_run_exists} AS has_active_run
                FROM items i
                WHERE i.project_id = {p}
                  AND i.status <> 'cancelled'
                ORDER BY i.id""",
            (project_id,),
        ).fetchall()

        items_for_board: List[board.ItemForBoard] = []
        for r in rows:
            d = dict(r)
            item_obj = _main._row_to_item(r, include_body=False)
            items_for_board.append(board.ItemForBoard(
                item=item_obj,
                status=d["status"],
                frozen_value=d.get("frozen"),
                has_active_run=bool(d.get("has_active_run")),
            ))

        projection = board.project_board(
            items=items_for_board,
            project=project,
        )

        response_columns: Dict[str, List[_main.ItemObject]] = {}
        for col_name in board.BOARD_COLUMNS:
            response_columns[col_name] = projection.columns.get(col_name, [])

        return _main.BoardResponse(
            project=projection.project,
            columns=response_columns,
            stats=_main.BoardStats(
                total=projection.stats.total,
                done=projection.stats.done,
                active=projection.stats.active,
                remaining=projection.stats.remaining,
            ),
        )
    finally:
        conn.close()


__all__ = ["router"]

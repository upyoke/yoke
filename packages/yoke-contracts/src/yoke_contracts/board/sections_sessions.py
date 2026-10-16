"""Read session facts for the connection-free board session renderer."""

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_cells import session_common_cells
from yoke_contracts.board.sections_sessions_holdings import session_holding_labels
from yoke_contracts.board.sections_sessions_scope import (
    session_rows,
    session_level_presentation,
)
from yoke_contracts.board.sections_sessions_rendering import _render_level
from yoke_contracts.board.session_data import _parked_cell, render_session_rows

__all__ = ["collect_session_rows", "render_sessions_section", "_parked_cell"]


def collect_session_rows(
    db: BoardDBLike, *, scope: str, active_only: bool
) -> list[dict]:
    """Resolve identities, usage and holdings once for each scoped session."""
    result = []
    for row in session_rows(db, scope=scope, active_only=active_only):
        (
            sid,
            executor,
            surface,
            model,
            requested,
            usage,
            mode,
            level,
            offered_at,
            _heartbeat,
            _workspace,
            project_id,
            *ended,
        ) = row
        cells = session_common_cells(
            db,
            sid,
            executor,
            surface,
            model,
            requested,
            usage,
            offered_at,
            project_id,
        )
        facts = dict(
            zip(
                ("session", "project", "executor", "model", "usage"), cells, strict=True
            )
        )
        facts.update(
            level=_render_level(
                level, session_level_presentation(db, project_id, level)
            ),
            mode=mode,
            offered_at=offered_at,
            ended_at=ended[0] if ended else None,
            holdings=session_holding_labels(db, sid),
        )
        result.append(facts)
    return result


def render_sessions_section(
    db: BoardDBLike, *, show_recent: bool = True, scope: str = "all"
) -> str:
    """Render the live roster and, when enabled, the three latest ended sessions."""
    return render_session_rows(
        collect_session_rows(db, scope=scope, active_only=True),
        collect_session_rows(db, scope=scope, active_only=False),
        show_recent=show_recent,
    )

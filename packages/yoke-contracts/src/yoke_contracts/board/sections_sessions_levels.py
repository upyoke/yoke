"""The execution levels a board session row is labeled against.

The board reads the same two stores the engine does — a project's
``session-routing`` override and the universe ``levels`` setting — and the
shared :func:`yoke_contracts.levels.resolve_effective_levels` decides which
wins, so a glyph on the board is the glyph the engine would stamp.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.levels import (
    LEVELS_KEY,
    Level,
    LevelsError,
    resolve_effective_levels,
)
from yoke_contracts.project_contract.project_keys import SESSION_ROUTING_CAPABILITY

_PROJECT_SQL = (
    "SELECT settings FROM project_capabilities WHERE project_id = %s AND type = %s"
)
_UNIVERSE_SQL = "SELECT value FROM universe_settings WHERE key = %s"


def _first_document(db: BoardDBLike, sql: str, params: tuple[Any, ...]) -> Any:
    has_query_quiet = getattr(db, "has_query_quiet", None)
    if callable(has_query_quiet) and not has_query_quiet(sql, params):
        return None
    rows = db.query_quiet(sql, params)
    if not rows:
        return None
    raw = rows[0][0]
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or "null"))
    except (TypeError, ValueError):
        return None


def board_levels(db: BoardDBLike, project_id: Optional[int]) -> tuple[Level, ...]:
    """Return the effective levels, or none when a stored document is unreadable."""
    project = (
        _first_document(db, _PROJECT_SQL, (project_id, SESSION_ROUTING_CAPABILITY))
        if project_id is not None
        else None
    )
    universe = _first_document(db, _UNIVERSE_SQL, (LEVELS_KEY,))
    try:
        return resolve_effective_levels(
            project if isinstance(project, dict) else None, universe
        )[0]
    except LevelsError:
        return ()


__all__ = ["board_levels"]

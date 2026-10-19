"""The execution levels a board session row is labeled against.

The board reads the same two stores the engine does — a project's
``session-routing`` override and the universe ``levels`` setting — and the
shared :func:`yoke_contracts.levels.resolve_effective_levels` decides which
wins, so a glyph on the board is the glyph the engine would stamp. A session
holding no level is explained from its model facts and the current published
catalog, through the same resolution the engine runs.
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
    level_reason,
)
from yoke_contracts.model_level_resolution import routing_effort_of, routing_model_of
from yoke_contracts.model_reference_catalog import validate_catalog
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.project_contract.project_keys import SESSION_ROUTING_CAPABILITY

_PROJECT_SQL = (
    "SELECT settings FROM project_capabilities WHERE project_id = %s AND type = %s"
)
_UNIVERSE_SQL = "SELECT value FROM universe_settings WHERE key = %s"
_SESSION_FACTS_SQL = (
    "SELECT model, requested_model, reasoning_effort, requested_reasoning_effort "
    "FROM harness_sessions WHERE session_id = %s"
)
_CATALOG_SQL = (
    "SELECT catalog_json FROM model_reference_revisions "
    "WHERE effective_at <= CURRENT_TIMESTAMP "
    "ORDER BY effective_at DESC, published_at DESC, revision_id DESC LIMIT 1"
)


def _first_document(db: BoardDBLike, sql: str, params: tuple[Any, ...]) -> Any:
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


def _current_records(db: BoardDBLike) -> tuple:
    document = _first_document(db, _CATALOG_SQL, ())
    if document is None:
        return ()
    try:
        return validate_catalog(document)
    except (ModelReferenceError, TypeError, ValueError):
        return ()


def board_level_reason(
    db: BoardDBLike, session_id: str, levels: tuple[Level, ...]
) -> str:
    """Why one session holds no level or a placed one (``""`` if neither)."""
    rows = db.query_quiet(_SESSION_FACTS_SQL, (session_id,))
    if not rows:
        return ""
    model, requested_model, effort, requested_effort = rows[0][:4]
    return (
        level_reason(
            levels,
            model=routing_model_of(model, requested_model),
            effort=routing_effort_of(effort, requested_effort, model),
            records=_current_records(db),
        )
        or ""
    )


__all__ = ["board_level_reason", "board_levels"]

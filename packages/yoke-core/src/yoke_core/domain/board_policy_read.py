"""Load board settings from ``project-policy`` for board rebuild + Overview."""

from __future__ import annotations

from typing import Any

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.policy_settings import (
    board_config_from_settings,
    board_scope_from_settings,
    board_settings_defaults,
)
from yoke_core.domain.project_policy_capabilities import (
    ensure_default_policy_capabilities,
    load_project_policy_settings,
)


def load_board_settings(conn: Any, project_id: int | None) -> dict[str, Any]:
    """Return the nested board object for a project, seeding defaults if needed."""

    if project_id is None:
        return board_settings_defaults()
    ensure_default_policy_capabilities(conn, int(project_id))
    settings = load_project_policy_settings(conn, int(project_id))
    board = settings.get("board")
    if isinstance(board, dict):
        return dict(board)
    return board_settings_defaults()


def resolve_board_config(conn: Any, project_id: int | None) -> BoardConfig:
    """Return BoardConfig from the project's DB board settings."""

    return board_config_from_settings(load_board_settings(conn, project_id))


def resolve_board_scope(
    conn: Any,
    project_id: int | None,
    *,
    explicit: str | None = None,
) -> str:
    """Resolve board scope from an explicit override or DB board settings."""

    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return board_scope_from_settings(
        load_board_settings(conn, project_id),
        project_id=project_id,
    )


__all__ = [
    "load_board_settings",
    "resolve_board_config",
    "resolve_board_scope",
]

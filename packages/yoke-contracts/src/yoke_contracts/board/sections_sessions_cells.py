"""Common cells for active/recent board session tables."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_scope import session_project_label
from yoke_contracts.executor_labels import EXECUTOR_EMOJI


def _resolve_executor_emoji(executor: str) -> str:
    """Resolve the emoji for an executor with family-prefix fallback."""
    if not executor:
        return ""
    if executor in EXECUTOR_EMOJI:
        return EXECUTOR_EMOJI[executor]
    if executor.startswith("claude-"):
        return EXECUTOR_EMOJI.get("claude-code", "")
    if executor.startswith("codex-"):
        return EXECUTOR_EMOJI.get("codex", "")
    return ""


def _display_model(model: Optional[str]) -> str:
    """Render the stored session model name verbatim."""
    return (model or "").strip() or "?"


def _display_session_id(session_id: Optional[str]) -> str:
    """Render the session id whole; an elided one names several sessions."""
    return session_id or "?"


def _render_executor(executor: str, executor_surface: Optional[str]) -> str:
    display_value = executor_surface or executor
    exec_emoji = _resolve_executor_emoji(display_value or "")
    return f"{exec_emoji} {display_value}" if exec_emoji else (display_value or "?")


def session_common_cells(
    db: BoardDBLike,
    sid: str,
    executor: str,
    executor_surface: Optional[str],
    model: Optional[str],
    project_id: object,
) -> list[str]:
    return [
        f"`{_display_session_id(sid)}`",
        session_project_label(db, project_id),
        _render_executor(executor, executor_surface),
        _display_model(model),
    ]

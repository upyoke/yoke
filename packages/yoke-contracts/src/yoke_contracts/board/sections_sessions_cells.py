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


_CURSOR_FAMILY_PREFIX = "cursor-"


def _display_model(
    model: Optional[str],
    executor: str,
    executor_surface: Optional[str],
) -> str:
    """Store the composed wire name; drop a redundant harness prefix here."""
    text = (model or "").strip() or "?"
    harness = (executor_surface or executor or "").lower()
    prefix = _CURSOR_FAMILY_PREFIX
    if (harness == "cursor" or harness.startswith(prefix)) and text.lower().startswith(
        prefix
    ):
        return text[len(prefix) :]
    return text


def _display_session_id(session_id: Optional[str]) -> str:
    """Keep session labels compact without hiding suffix differences."""
    if not session_id:
        return "?"
    if len(session_id) <= 18:
        return session_id
    return f"{session_id[:8]}...{session_id[-4:]}"


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
        _display_model(model, executor, executor_surface),
    ]

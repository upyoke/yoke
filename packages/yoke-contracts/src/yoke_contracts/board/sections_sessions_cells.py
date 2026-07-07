"""Common cells for active/recent board session tables."""

from __future__ import annotations

from typing import Dict, Optional

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_scope import session_project_label


_EXECUTOR_EMOJI: Dict[str, str] = {
    "claude-code": "\U0001f916",     # robot (coarse Claude family)
    "claude-desktop": "\U0001f34e",  # 🍎 apple (desktop)
    "claude-vscode": "\U0001fa9f",   # window
    "claude-cli": "\U0001f4df",      # 📟 pager
    "codex": "\U0001f4d5",           # 📕 closed book (coarse Codex family)
    "codex-desktop": "\U0001f4bb",   # 💻 laptop
    "codex-vscode": "\U0001fa84",    # magic wand
    "codex-cli": "📠",     # 📠 fax
}


def _resolve_executor_emoji(executor: str) -> str:
    """Resolve the emoji for an executor with family-prefix fallback."""
    if not executor:
        return ""
    if executor in _EXECUTOR_EMOJI:
        return _EXECUTOR_EMOJI[executor]
    if executor.startswith("claude-"):
        return _EXECUTOR_EMOJI.get("claude-code", "")
    if executor.startswith("codex-"):
        return _EXECUTOR_EMOJI.get("codex", "")
    return ""


def _display_session_id(session_id: Optional[str]) -> str:
    """Keep session labels compact without hiding suffix differences."""
    if not session_id:
        return "?"
    if len(session_id) <= 18:
        return session_id
    return f"{session_id[:8]}...{session_id[-4:]}"


def _render_executor(executor: str, executor_display_name: Optional[str]) -> str:
    display_value = executor_display_name or executor
    exec_emoji = _resolve_executor_emoji(display_value or "")
    return (
        f"{exec_emoji} {display_value}"
        if exec_emoji
        else (display_value or "?")
    )


def session_common_cells(
    db: BoardDBLike,
    sid: str,
    executor: str,
    executor_display_name: Optional[str],
    model: Optional[str],
    project_id: object,
) -> list[str]:
    return [
        f"`{_display_session_id(sid)}`",
        session_project_label(db, project_id),
        _render_executor(executor, executor_display_name),
        model or "?",
    ]

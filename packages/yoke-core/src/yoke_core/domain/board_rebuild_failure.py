"""Non-fatal failure reporting for automatic board rebuilds."""

from __future__ import annotations

from typing import TextIO


BOARD_REBUILD_FAILED_EVENT_NAME = "BoardRebuildFailed"
RECOVERY_COMMAND = "yoke board rebuild"


def record_board_rebuild_failure(reason: str, out: TextIO) -> str:
    """Print and record one rebuild failure without raising it."""
    detail = str(reason or "unknown board rebuild failure").strip()
    message = (
        f"[board-rebuild-failed] {detail}. The status change remains "
        f"committed; retry with `{RECOVERY_COMMAND}`."
    )
    print(message, file=out)
    try:
        from yoke_core.domain.events import emit_event
        from yoke_core.domain.session_ambient_identity import (
            resolve_ambient_session_id,
        )

        emit_event(
            BOARD_REBUILD_FAILED_EVENT_NAME,
            event_kind="workflow",
            event_type="board_rebuild",
            source_type="backend",
            session_id=resolve_ambient_session_id() or "",
            severity="WARN",
            outcome="failed",
            tool_name="automatic board rebuild",
            exit_code=1,
            context={"reason": detail, "recovery_command": RECOVERY_COMMAND},
        )
    except Exception:
        # Event recording is best-effort and cannot make the generated view
        # authoritative over the status mutation it follows.
        pass
    return message


__all__ = [
    "BOARD_REBUILD_FAILED_EVENT_NAME",
    "RECOVERY_COMMAND",
    "record_board_rebuild_failure",
]

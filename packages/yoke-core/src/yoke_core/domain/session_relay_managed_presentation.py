"""Distinguish Yoke-managed Claude sessions from operator-opened sessions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from yoke_contracts.session_control.presentation import CLAUDE_LOCAL_PRESENTATION
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_types import LaunchRequest


_CLAUDE_CLI_SURFACE = "claude-cli"
_CLAUDE_SURFACE_PREFIX = "claude-"


def normalize_launch_presentation(request: LaunchRequest) -> LaunchRequest:
    """Make the omitted Claude policy explicit before validation/persistence."""
    if (
        not request.executor_surface.startswith(_CLAUDE_SURFACE_PREFIX)
        or request.presentation
    ):
        return request
    return replace(request, presentation=CLAUDE_LOCAL_PRESENTATION)


def managed_session_presentation(
    conn: Any,
    *,
    session_id: str,
    surface: str,
) -> str | None:
    """Return local-only for a Yoke-launched Claude session, else no opinion."""
    if surface != _CLAUDE_CLI_SURFACE or not session_id:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT 1 FROM session_launches "
        f"WHERE registered_session_id={marker} AND state='succeeded' LIMIT 1",
        (session_id,),
    ).fetchone()
    return CLAUDE_LOCAL_PRESENTATION if row is not None else None


__all__ = ["managed_session_presentation", "normalize_launch_presentation"]

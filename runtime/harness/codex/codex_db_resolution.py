"""Codex hook DB-path resolution."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_yoke_db(root: str) -> str:
    """Return an explicit test DB override, or ``""`` for Postgres authority."""
    connected_env = None
    if root:
        try:
            from yoke_core.domain import yoke_connected_env

            connected_env = yoke_connected_env.load_active(Path(root))
        except Exception:
            connected_env = None

    current = os.environ.get("YOKE_DB", "")
    if current:
        try:
            from yoke_core.domain.yoke_connected_env_retired_db import (
                retired_yoke_db_reason,
            )

            if retired_yoke_db_reason(connected_env):
                return ""
        except Exception:
            pass
        return current
    return ""


__all__ = ["resolve_yoke_db"]

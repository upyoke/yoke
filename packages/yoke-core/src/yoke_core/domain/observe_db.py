"""Backend-aware event DB helpers for observe hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def normalize_observe_db_path(db_path: Optional[str]) -> Optional[str]:
    """Drop retired canonical SQLite paths under connected Postgres authority."""
    if not db_path:
        return None
    try:
        from yoke_core.domain import yoke_connected_env
        from yoke_core.domain.yoke_connected_env_retired_db import (
            retired_yoke_db_path_reason,
        )

        db_file = Path(db_path).expanduser().resolve(strict=False)
        env = yoke_connected_env.load_active(db_file.parent.parent)
        if retired_yoke_db_path_reason(env, str(db_file)):
            return None
    except Exception:
        pass
    return db_path


def connect_observe_db():
    """Connect directly to the active Postgres event authority."""
    from yoke_core.domain import db_backend

    return db_backend.connect()


__all__ = [
    "connect_observe_db",
    "normalize_observe_db_path",
]

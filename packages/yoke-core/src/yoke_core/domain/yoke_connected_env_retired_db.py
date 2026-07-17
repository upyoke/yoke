"""Retired file-backed authority guards for connected environments."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_core.domain.yoke_connected_env import ConnectedEnv


def retired_yoke_db_reason(
    env: Optional[ConnectedEnv],
    yoke_db_env: str = "YOKE_DB",
) -> Optional[str]:
    raw = os.environ.get(yoke_db_env)
    if not raw:
        return None
    return retired_yoke_db_path_reason(env, raw)


def retired_yoke_db_path_reason(
    env: Optional[ConnectedEnv],
    raw_path: str,
) -> Optional[str]:
    if env is None or env.backend != "postgres":
        return None
    try:
        requested = Path(raw_path).expanduser().resolve(strict=False)
    except OSError:
        return None
    if requested.name != "yoke.db" or requested.parent.name != "data":
        return None
    return (
        f"retired local SQLite authority {requested} under connected "
        f"environment {env.project}/{env.environment} ({env.binding_path})"
    )


def retired_db_guard_reason_for_env(
    env: Optional[ConnectedEnv],
    *,
    yoke_db_env: str = "YOKE_DB",
) -> Optional[str]:
    retired_reason = retired_yoke_db_reason(env, yoke_db_env)
    if retired_reason:
        return retired_reason
    if os.environ.get(yoke_db_env):
        return None
    if env and env.backend == "postgres":
        return (
            f"connected environment {env.project}/{env.environment} "
            f"({env.binding_path})"
        )
    return None


__all__ = [
    "retired_db_guard_reason_for_env",
    "retired_yoke_db_path_reason",
    "retired_yoke_db_reason",
]

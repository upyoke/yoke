"""Schema fragments and migration support for the GitHub sync switch."""

from __future__ import annotations

from typing import Any

from yoke_contracts.project_contract.github_sync_mode import (
    GITHUB_SYNC_DISABLED,
    GITHUB_SYNC_ENABLED,
)
from yoke_core.domain import db_backend


def github_sync_mode_column_sql() -> str:
    """Return the portable DDL for a new fail-closed sync-mode column."""
    return f"TEXT NOT NULL DEFAULT '{GITHUB_SYNC_DISABLED}'"


def normalize_github_sync_modes(conn: Any) -> None:
    """Normalize legacy or empty modes to the fail-closed value."""
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE projects SET github_sync_mode={placeholder} "
        "WHERE github_sync_mode IS NULL OR TRIM(github_sync_mode) = '' "
        f"OR github_sync_mode NOT IN ({placeholder}, {placeholder})",
        (GITHUB_SYNC_DISABLED, GITHUB_SYNC_ENABLED, GITHUB_SYNC_DISABLED),
    )
    conn.commit()


__all__ = ["github_sync_mode_column_sql", "normalize_github_sync_modes"]

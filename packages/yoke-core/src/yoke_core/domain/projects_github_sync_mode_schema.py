"""Schema fragment for the GitHub sync switch."""

from yoke_contracts.project_contract.github_sync_mode import GITHUB_SYNC_DISABLED


def github_sync_mode_column_sql() -> str:
    """Return the portable DDL for a new fail-closed sync-mode column."""
    return f"TEXT NOT NULL DEFAULT '{GITHUB_SYNC_DISABLED}'"


__all__ = ["github_sync_mode_column_sql"]

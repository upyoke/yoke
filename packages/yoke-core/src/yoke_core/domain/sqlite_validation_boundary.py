"""SQLite validation/import boundary guards.

SQLite remains valid for generic project validation files and archived
one-time import artifacts. It is not a Yoke control-plane authority.
This module centralizes the retired root ``data/yoke.db`` refusal so the
remaining SQLite readers fail closed on the dangerous path while still
accepting explicit external validation/archive files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


_RETIRED_ROOT_DB_PARTS = ("data", "yoke.db")


def is_retired_root_yoke_db_path(path: Union[str, Path]) -> bool:
    """Return True for the retired root ``data/yoke.db`` authority path."""
    parts = Path(path).parts
    return len(parts) >= 2 and parts[-2:] == _RETIRED_ROOT_DB_PARTS


def reject_retired_root_yoke_db_path(
    path: Union[str, Path],
    *,
    surface: str,
) -> None:
    """Fail closed when a generic SQLite surface points at root yoke.db."""
    if is_retired_root_yoke_db_path(path):
        raise ValueError(
            f"{surface} refuses retired Yoke control-plane SQLite path "
            f"{Path(path)}; use Postgres authority for Yoke and reserve "
            "SQLite for explicit external validation or archived import files."
        )


__all__ = [
    "is_retired_root_yoke_db_path",
    "reject_retired_root_yoke_db_path",
]

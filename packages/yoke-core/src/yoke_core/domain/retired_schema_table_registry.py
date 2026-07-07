"""Table-level helpers for retired-schema registry entries."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from yoke_core.domain.retired_schema_registry import (
    RetiredSurface,
    load_registry,
)


def is_retired_table(
    project: str,
    table: str,
    *,
    repo_root: Optional[Path] = None,
) -> bool:
    """Return ``True`` when the whole table is registered as retired."""
    return any(
        record.project == project
        and record.table == table
        and record.column is None
        for record in load_registry(repo_root)
    )


def lookup_module_for_table(
    project: str,
    table: str,
    *,
    repo_root: Optional[Path] = None,
) -> Optional[str]:
    """Return the migration module that retired this table, if any."""
    for record in load_registry(repo_root):
        if (
            record.project == project
            and record.table == table
            and record.column is None
        ):
            return record.module
    return None


def list_all_retired_tables(
    *, repo_root: Optional[Path] = None
) -> List[RetiredSurface]:
    """Return every registry entry that retires an entire table."""
    return [
        record
        for record in load_registry(repo_root)
        if record.column is None
    ]


__all__ = [
    "is_retired_table",
    "lookup_module_for_table",
    "list_all_retired_tables",
]

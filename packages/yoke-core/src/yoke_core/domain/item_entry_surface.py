"""Typed entry-surface authorization for work-item creation."""

from __future__ import annotations

import os
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_runtime import WorkflowRuntime

ITEM_ENTRY_SURFACE_ENV = "YOKE_ITEM_ENTRY_SURFACE"
ENTRY_SURFACE_HARNESS_SKILL = "harness_skill"

MISSING_ENTRY_SURFACE_MESSAGE = (
    "Work-item creation requires a typed entry surface. Use the workflow's "
    "registered web form, CLI, harness skill, or promotion operation."
)


def _dsn_dbname(dsn: str) -> Optional[str]:
    for part in dsn.split():
        if part.startswith("dbname="):
            return part.split("=", 1)[1]
    return None


def is_test_isolation(db_path: Optional[str] = None) -> bool:
    """Return whether a path-shaped token is backed by a disposable DB."""
    if not db_path:
        return False
    dbname = _dsn_dbname(os.environ.get(db_backend.PG_DSN_ENV, ""))
    return bool(
        dbname and dbname.startswith(db_backend.POSTGRES_TEST_DB_PREFIX)
    )


def resolve_entry_surface(entry_surface: Optional[str] = None) -> Optional[str]:
    """Resolve an explicit entry surface or its subprocess environment form."""
    value = entry_surface or os.environ.get(ITEM_ENTRY_SURFACE_ENV)
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def enforce_item_entry_allowed(
    *,
    workflow: WorkflowRuntime,
    entry_surface: Optional[str] = None,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Optional[str]:
    """Return an error when creation is not allowed through this surface."""
    resolved = resolve_entry_surface(entry_surface)
    if resolved is None:
        if dry_run or is_test_isolation(db_path):
            return None
        return MISSING_ENTRY_SURFACE_MESSAGE
    if workflow.allows_entry_surface(resolved):
        return None
    return (
        f"Workflow {workflow.workflow_id}@{workflow.version} does not allow "
        f"the {resolved!r} entry surface."
    )


__all__ = [
    "ENTRY_SURFACE_HARNESS_SKILL",
    "ITEM_ENTRY_SURFACE_ENV",
    "MISSING_ENTRY_SURFACE_MESSAGE",
    "enforce_item_entry_allowed",
    "is_test_isolation",
    "resolve_entry_surface",
]

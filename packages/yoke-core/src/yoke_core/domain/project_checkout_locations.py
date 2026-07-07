"""Machine-local checkout resolution for project-scoped source-dev flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_contracts.machine_config.schema import normalize_project_id

from yoke_core.domain import db_backend, machine_config, project_settings
from yoke_core.domain.project_identity import resolve_project_id


def checkout_for_project_id(
    project_id: int | None,
    *,
    config_path: str | Path | None = None,
) -> Optional[Path]:
    """Return this machine's checkout path for a project id, if configured."""

    if project_id is None:
        return None
    target = int(project_id)
    projects = machine_config.load_config(config_path).get("projects", {})
    if not isinstance(projects, dict):
        return None
    for checkout, entry in sorted(projects.items()):
        if not isinstance(entry, dict):
            continue
        mapped = normalize_project_id(entry.get("project_id"))
        if mapped == target:
            return Path(str(checkout)).expanduser()
    return None


def checkout_for_project(
    conn: Any,
    project: str,
    *,
    config_path: str | Path | None = None,
) -> Optional[Path]:
    """Resolve a project slug/id to this machine's checkout path."""

    try:
        project_id = resolve_project_id(conn, project)
    except LookupError:
        return None
    return checkout_for_project_id(project_id, config_path=config_path)


def item_worktree_path(
    conn: Any,
    item_id: int,
    *,
    config_path: str | Path | None = None,
) -> Optional[Path]:
    """Return this machine's worktree path for an item, if one is mapped."""

    p = _placeholder(conn)
    row = conn.execute(
        "SELECT worktree, project_id FROM items WHERE id = " + p + " LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    branch = _row_value(row, "worktree", 0)
    project_id = normalize_project_id(_row_value(row, "project_id", 1))
    return worktree_path_for_branch(
        project_id, branch, config_path=config_path,
    )


def epic_task_worktree_path(
    conn: Any,
    epic_id: int,
    task_num: int,
    *,
    config_path: str | Path | None = None,
) -> Optional[Path]:
    """Return this machine's worktree path for an epic task, if mapped."""

    p = _placeholder(conn)
    row = conn.execute(
        "SELECT et.worktree, i.project_id FROM epic_tasks et "
        "JOIN items i ON i.id = et.epic_id "
        f"WHERE et.epic_id = {p} AND et.task_num = {p} LIMIT 1",
        (int(epic_id), int(task_num)),
    ).fetchone()
    if row is None:
        return None
    branch = _row_value(row, "worktree", 0)
    project_id = normalize_project_id(_row_value(row, "project_id", 1))
    return worktree_path_for_branch(
        project_id, branch, config_path=config_path,
    )


def worktree_path_for_branch(
    project_id: int | None,
    branch: Any,
    *,
    config_path: str | Path | None = None,
) -> Optional[Path]:
    """Compose the local worktree path for a project id and branch token."""

    branch_str = str(branch or "").strip()
    if not branch_str:
        return None
    checkout = checkout_for_project_id(project_id, config_path=config_path)
    if checkout is None:
        return None
    worktrees_dir = project_settings.get_project_str(
        checkout, "worktrees_dir", config_path=config_path,
    )
    return checkout / worktrees_dir / branch_str


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


__all__ = [
    "checkout_for_project",
    "checkout_for_project_id",
    "epic_task_worktree_path",
    "item_worktree_path",
    "worktree_path_for_branch",
]

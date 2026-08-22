"""Item implementation-lane resolution surface.

Owns ``ResolvedWorktree`` and ``resolve_item_worktree`` — the DB-backed
lookup that maps a backlog item to its worktree path or epic task lane set,
branch data, repo, and project. Imports the shared low-level primitives from
:mod:`yoke_core.domain.worktree` and the path-resolution helpers from
:mod:`yoke_core.domain.worktree_paths`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain import project_settings
from yoke_core.domain.item_worktree_resolution import (
    recorded_item_worktree_lanes,
    resolve_live_branch,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.worktree_paths import (
    _resolve_config_path,
    _resolve_repo_root_from_cwd,
    is_git_worktree,
    resolve_main_root,
)


@dataclass
class ResolvedWorktree:
    """Result of resolving an item's worktree."""

    path: str
    branch: str
    repo: str
    project: str
    exists: bool
    scope: str = "item"
    paths: tuple[str, ...] = ()
    branches: tuple[str, ...] = ()

    @property
    def has_multiple(self) -> bool:
        """Return True when the item resolves to multiple worktree lanes."""
        return len(self.paths) > 1


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_item_worktree(
    item_ref: str | int,
    *,
    db_path: Optional[str] = None,
    scripts_dir: Optional[str] = None,
) -> ResolvedWorktree:
    """Resolve the implementation worktree lane set for a backlog item.

    Parameters
    ----------
    item_ref:
        Item reference.
    db_path:
        Explicit DB path.  When ``None``, uses ``YOKE_DB`` or walks up.
    scripts_dir:
        Path to the scripts directory.  When ``None``, resolves from this file.

    Raises
    ------
    ValueError:
        If the item ID is invalid.
    LookupError:
        If the item is not found in the DB.
    RuntimeError:
        If the repo root cannot be resolved.
    """
    from yoke_core.domain.db_helpers import connect, query_scalar

    from yoke_core.domain.yok_n_parser import parse_item_argument

    conn = connect(path=db_path)
    try:
        item_num = parse_item_argument(item_ref, conn=conn)

        if scripts_dir is None:
            from yoke_core.api.repo_root import find_repo_root

            scripts_dir = str(
                find_repo_root(Path(__file__))
                / ".agents" / "skills" / "yoke" / "scripts"
            )

        p = _placeholder(conn)
        status = query_scalar(
            conn, f"SELECT status FROM items WHERE id = {p}", (item_num,)
        )
        if status is None:
            from yoke_core.domain.project_identity import render_item_ref

            raise LookupError(f"item {render_item_ref(conn, item_num)} not found")

        project_row = conn.execute(
            "SELECT p.slug AS project "
            "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (item_num,),
        ).fetchone()
        item_project = (
            project_row["project"]
            if project_row and hasattr(project_row, "keys")
            else project_row[0]
            if project_row
            else None
        )
        if not item_project or item_project == "null":
            item_project = "yoke"

        checkout = checkout_for_project(conn, item_project)
        repo_root = str(checkout) if checkout is not None else None

        # Resolve repo root — try local checkout mapping first, then fallback
        if not repo_root:
            repo_root = _resolve_repo_root_from_cwd()
            if not repo_root:
                try:
                    repo_root = resolve_main_root()
                except RuntimeError:
                    repo_root = None

        if not repo_root:
            raise RuntimeError(
                f"could not resolve repo root for project '{item_project}'"
            )

        # Resolve worktrees dir
        config_path = _resolve_config_path(repo_root)
        wt_dir = project_settings.get_project_str(
            repo_root,
            "worktrees_dir",
            config_path=config_path,
        )

        lanes, lane_scope = recorded_item_worktree_lanes(
            conn,
            item_num,
            repo_root,
            wt_dir,
        )
        if lanes:
            paths = tuple(path for _, path in lanes)
            branches = tuple(
                resolve_live_branch(path, branch) for branch, path in lanes
            )
            return ResolvedWorktree(
                path=paths[0] if len(paths) == 1 else "",
                branch=branches[0] if len(branches) == 1 else "",
                repo=repo_root,
                project=item_project,
                exists=all(is_git_worktree(path) for path in paths),
                scope=lane_scope,
                paths=paths,
                branches=branches,
            )

        return ResolvedWorktree(
            path="",
            branch="",
            repo=repo_root,
            project=item_project,
            exists=False,
            scope=lane_scope,
            paths=(),
            branches=(),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Resolve item worktree lane(s). Skill prose entry point."
    )
    parser.add_argument("item_ref", help="Item reference (e.g. YOK-N).")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--branches",
        action="store_true",
        help="Print branch name(s) one per line (default).",
    )
    grp.add_argument(
        "--paths",
        action="store_true",
        help="Print worktree path(s) one per line.",
    )
    grp.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print full resolution as JSON.",
    )
    args = parser.parse_args()
    try:
        result = resolve_item_worktree(args.item_ref)
    except (ValueError, LookupError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.paths:
        for path in result.paths:
            print(path)
    elif args.as_json:
        print(
            json.dumps(
                {
                    "path": result.path,
                    "branch": result.branch,
                    "repo": result.repo,
                    "project": result.project,
                    "exists": result.exists,
                    "scope": result.scope,
                    "paths": list(result.paths),
                    "branches": list(result.branches),
                    "has_multiple": result.has_multiple,
                }
            )
        )
    else:
        for branch in result.branches:
            print(branch)

"""Merge-worktree preparation data and context resolution."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw


_TASK_TERMINAL_SUCCESS = ("done", "reviewed-implementation", "implemented", "release")


@dataclass
class MergeArgs:
    """Parsed command-line arguments."""
    branch: str
    target: str = "main"
    epic_ref: Optional[str] = None
    local_merge: bool = False
    force_lock: bool = False
    keep_remote: bool = False
    skip_simulation: bool = False


@dataclass
class MergeContext:
    """Accumulated state during the merge workflow."""
    args: MergeArgs
    repo_root: str = ""
    yoke_repo_root: str = ""
    worktree_path: str = ""
    epic_id: Optional[str] = None
    item_id: Optional[str] = None
    project: Optional[str] = None
    generated_files: list[str] = field(default_factory=list)
    branch_changed_files: list[str] = field(default_factory=list)
    used_merge_fallback: bool = False
    conn: Optional[Any] = None
    # SHA that origin/{target} pointed at immediately after we
    # pushed local target forward (before trial merge).  Used to detect a
    # race where the target moves underfoot between validation and PR merge.
    target_sha_at_validation: Optional[str] = None

    # File classification patterns
    doc_files: list[str] = field(default_factory=lambda: [
        "AGENTS.md", "CLAUDE.md", "README.md", "docs/*",
    ])
    yoke_gen_files: list[str] = field(default_factory=lambda: [
        # Generated view conflict classification for project-local board
        # render outputs. State truth remains in Postgres.
        ".yoke/BOARD.md",
        ".yoke/BOARD.md.ts",
    ])


@dataclass
class ConflictInfo:
    """Per-file conflict classification."""
    path: str
    classification: str  # "generated", "doc", "yoke-gen", "additive", "overlapping"
    auto_resolvable: bool


def _sql_task_terminal_success_list() -> str:
    return ", ".join(f"'{s}'" for s in _TASK_TERMINAL_SUCCESS)


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _matches_glob(filepath: str, patterns: list[str]) -> bool:
    """Check if filepath matches any of the given glob patterns."""
    import fnmatch
    for pattern in patterns:
        if fnmatch.fnmatch(filepath, pattern):
            return True
    return False


def validate_args(args: MergeArgs) -> Optional[str]:
    """Validate arguments. Returns error message or None."""
    if not args.branch:
        return (
            "Usage: python3 -m yoke_core.engines.merge_worktree "
            "[--local] [--keep-remote] [--skip-simulation] <branch> "
            "[target-branch] [epic-ref]"
        )

    # Reject retired branch naming.
    if args.branch.startswith("issue/YOK-") or args.branch.startswith("epic/YOK-"):
        return f"Error: legacy branch naming '{args.branch}' is retired."

    return None


def resolve_context(args: MergeArgs) -> MergeContext:
    """Resolve full merge context from arguments."""
    from yoke_core.domain.worktree import resolve_main_root

    mw = _parent()

    ctx = MergeContext(args=args)

    # Get repo root -- worktree-aware: resolve to the owning
    # main repo, not the CWD-relative worktree root.  This ensures all
    # downstream git operations (local target sync, branch cleanup, etc.)
    # run against the main repo even when the engine is invoked from a
    # worktree CWD.
    try:
        ctx.repo_root = resolve_main_root()
    except RuntimeError:
        raise RuntimeError("Not in a git repository")
    ctx.yoke_repo_root = ctx.repo_root

    # Parse item ID from branch name
    match = re.search(r"YOK-(\d+)", args.branch)
    if match:
        ctx.item_id = match.group(1)

    # Resolve epic ID
    ctx.epic_id = args.epic_ref
    if ctx.epic_id:
        # Resolve YOK-N or numeric
        clean_id = re.sub(r"^[Yy][Oo][Kk]-", "", ctx.epic_id).lstrip("0") or "0"
        conn = None
        try:
            conn = mw._connect()
            row = conn.execute(
                f"SELECT CAST(id AS TEXT) FROM items WHERE id={_p(conn)} LIMIT 1",
                (int(clean_id),),
            ).fetchone()
            if row:
                ctx.epic_id = row[0]
        except Exception:  # noqa: BLE001 - DB context is advisory here.
            pass
        finally:
            if conn is not None:
                conn.close()

    # Guard: standalone item branches need YOKE_DONE_TRANSITION
    if (not ctx.epic_id or ctx.epic_id == "null") and args.branch.startswith("YOK-"):
        if os.environ.get("YOKE_DONE_TRANSITION", "0") != "1":
            raise RuntimeError(
                f"merge_worktree called for standalone item branch '{args.branch}' "
                "without an epic ID. Standalone items must be merged via "
                "`python3 -m yoke_core.engines.done_transition`."
            )

    # Project-aware repo root resolution
    if ctx.item_id:
        conn = None
        try:
            conn = mw._connect()
            row = conn.execute(
                "SELECT p.slug FROM items i LEFT JOIN projects p ON p.id = i.project_id "
                f"WHERE i.id={_p(conn)}",
                (int(ctx.item_id),),
            ).fetchone()
            if row and row[0] and row[0] != "yoke":
                from yoke_core.domain.project_checkout_locations import (
                    checkout_for_project,
                )

                ctx.project = row[0]
                checkout = checkout_for_project(conn, ctx.project)
                if checkout is None:
                    raise RuntimeError(
                        f"project '{ctx.project}' has no machine-local "
                        "checkout mapping"
                    )
                ctx.repo_root = str(checkout)
                # Resolve default branch for non-yoke projects
                if not args.target or args.target == "main":
                    branch_row = conn.execute(
                        f"SELECT default_branch FROM projects WHERE slug={_p(conn)}",
                        (ctx.project,),
                    ).fetchone()
                    if branch_row and branch_row[0]:
                        args.target = branch_row[0]
            else:
                ctx.project = row[0] if row else None
        except Exception:  # noqa: BLE001 - default Yoke repo context is safe.
            pass
        finally:
            if conn is not None:
                conn.close()

    if not args.target:
        from yoke_core.domain import project_settings

        args.target = project_settings.get_project_str(ctx.repo_root, "base_branch")

    # Resolve worktree path for branch
    ctx.worktree_path = _find_worktree(args.branch, ctx.repo_root)

    return ctx


def _find_worktree(branch: str, repo_root: str) -> str:
    """Find the worktree path for a branch, or fall back to repo root."""
    mw = _parent()
    result = mw._run_git(["worktree", "list", "--porcelain"], cwd=repo_root, capture=True)
    if result.returncode != 0:
        return repo_root

    current_wt = ""
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_wt = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            return current_wt

    return repo_root

from yoke_core.engines.merge_worktree_prepare_preflight import preflight_checks  # noqa: E402,F401
from yoke_core.engines.merge_worktree_prepare_state import (  # noqa: E402,F401
    check_and_clean_root_dirty_state,
    prune_agent_worktrees,
    extract_generated_files,
    _pre_merge_integration,
    _stash_classify_gate,
)

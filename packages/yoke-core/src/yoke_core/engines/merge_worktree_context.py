"""Shared merge-worktree argument and context types."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MergeArgs:
    """Parsed command-line arguments."""

    branch: str
    source_sha: Optional[str] = None
    target: str = "main"
    epic_ref: Optional[str] = None
    item_id: Optional[int] = None
    expected_repo_root: Optional[str] = None
    local_merge: bool = False
    force_lock: bool = False
    keep_remote: bool = False
    skip_simulation: bool = False
    # Permission to merge a branch that belongs to an item rather than an
    # epic lane. Held by the standalone-item merge operation, which owns the
    # surrounding item bookkeeping the engine does not.
    standalone: bool = False
    # Force local post-rebase verification even when the project declares a
    # ci_workflow_file capability (offline / deliberate local execution).
    local_verification: bool = False


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
    # pushed local target forward (before trial merge). Used to detect a
    # race where the target moves underfoot between validation and PR merge.
    target_sha_at_validation: Optional[str] = None

    # File classification patterns.
    doc_files: list[str] = field(
        default_factory=lambda: ["AGENTS.md", "CLAUDE.md", "README.md", "docs/*"]
    )
    yoke_gen_files: list[str] = field(
        # Generated view conflict classification for project-local board
        # render outputs. State truth remains in Postgres.
        default_factory=lambda: [".yoke/BOARD.md", ".yoke/BOARD.md.ts"]
    )


def _matches_glob(filepath: str, patterns: list[str]) -> bool:
    """Check if filepath matches any of the given glob patterns."""
    return any(fnmatch.fnmatch(filepath, pattern) for pattern in patterns)

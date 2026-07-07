"""Recognized project setting keys and defaults.

One source of truth for each key's source default and one-line meaning.
``project-policy`` owns shared project behavior in the DB; local-only keys
describe machine checkout facts.
"""

from __future__ import annotations

from typing import Dict, Tuple

RECOGNIZED_PROJECT_KEYS: Dict[str, Tuple[str, str]] = {
    "base_branch": (
        "main",
        "trunk branch worktrees branch from and merges land on",
    ),
    "wip_cap": (
        "5",
        "scheduler WIP cap for conduct-eligible items",
    ),
    "worktrees_dir": (
        ".worktrees",
        "checkout-relative directory holding linked worktrees",
    ),
    "default_priority": (
        "medium",
        "priority assigned to new backlog items when none is given",
    ),
    "merge_conflict_threshold": (
        "2",
        "rebase auto-resolve passes allowed before falling back to merge",
    ),
    "max_attempts": (
        "5",
        "dispatch attempts per epic task before the chain halts",
    ),
    "file_line_limit": (
        "350",
        "authored-file line limit enforced by local hooks and check commands",
    ),
}

LOCAL_PROJECT_KEYS = frozenset({"worktrees_dir"})
DB_PROJECT_POLICY_KEYS = tuple(
    key for key in RECOGNIZED_PROJECT_KEYS if key not in LOCAL_PROJECT_KEYS
)

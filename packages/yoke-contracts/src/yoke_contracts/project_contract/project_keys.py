"""Recognized project setting keys and defaults.

One source of truth for each key's source default and one-line meaning.
``project-policy`` owns shared project behavior in the DB; local-only keys
describe machine checkout facts. Machine-local runtime tunables are the
separate registry in
``yoke_contracts.machine_config.settings_keys``.

The authored-file line limit is deliberately not a key here: it must be
enforceable by an offline git hook in a fresh clone, so it is checked-in
project-file policy owned by
``yoke_contracts.project_contract.file_line_policy``.
"""

from __future__ import annotations

from typing import Dict, Tuple

# The two capability rows that carry DB-owned project configuration. Named
# here so the machine-settings registry can point at the real authority
# without importing upward into the core package.
PROJECT_POLICY_CAPABILITY = "project-policy"
SESSION_ROUTING_CAPABILITY = "session-routing"

RECOGNIZED_PROJECT_KEYS: Dict[str, Tuple[str, str]] = {
    "base_branch": (
        "main",
        "trunk branch worktrees branch from and merges land on",
    ),
    "wip_cap": (
        "30",
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
}

LOCAL_PROJECT_KEYS = frozenset({"worktrees_dir"})
DB_PROJECT_POLICY_KEYS = tuple(
    key for key in RECOGNIZED_PROJECT_KEYS if key not in LOCAL_PROJECT_KEYS
)

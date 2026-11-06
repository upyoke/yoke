# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import shlex

import pytest

from yoke_core.tools import watch_merge

from yoke_core.tools._watch_runner import filter_match

pytestmark = pytest.mark.usefixtures("bound_project_context")

PRIMARY_ITEM_NUM = 42

PRIMARY_ITEM = f"YOK-{PRIMARY_ITEM_NUM}"

SECONDARY_ITEM_NUM = 99

SECONDARY_ITEM = f"YOK-{SECONDARY_ITEM_NUM}"

FAKE_ITEM_NUM = 9

FAKE_ITEM = f"YOK-{FAKE_ITEM_NUM}"

MERGE_WORKTREE_FIXTURE_LINES: list[str] = [
    f"Merging branch: {PRIMARY_ITEM} → main",
    f"Worktree: /repo/.worktrees/{PRIMARY_ITEM}",
    "Error: merge phase 'rebase' failed (exit 1).",
    "Error: GitHub CLI (gh) is required for merge.",
    f"Error: branch '{SECONDARY_ITEM}' does not exist as a local ref.",
    f"Warning: branch mismatch detected. Correcting to {PRIMARY_ITEM}.",
    "Merge lock error: lease held by other session.",
    "fatal: not a git repository",
]

NOISE_LINES: list[str] = [
    "  some indented detail",
    "Title: Some title",  # detail-only — should not match (no leading sentinel)
    "Old status: implementing",
    "Type: issue",
    "Project: yoke (repo: /repo)",
    "ordinary diagnostic detail",
]

"""Tests for yoke_core.domain — lifecycle, approval, runs, queries, and board.

Shared helpers used by the split test modules:
  - test_domain_items_lifecycle.py: lifecycle invariants, validation,
    terminal/task-terminal-success, progression, SQL fragments
  - test_domain_items_epic.py: epic-workflow-type validation and progression
  - test_domain_items_approval.py: approval domain (halt-state, flow stages,
    resolution, ApprovalPath)
  - test_domain_sessions.py: runs, queries, and board tests
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_repo_root() -> str:
    """Return the repo root, works from the worktree too."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

"""Shared helpers for test_dependency_planning_*.py modules.

Pure helpers (no pytest fixtures) — safe to import from any test module
without triggering pytest fixture-discovery side effects. The naming
convention `<stem>_test_helpers.py` keeps pytest from collecting an
empty test module.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.test_dependency_schema import create_dependency_test_db


def create_test_db() -> Any:
    """Create a disposable DB with the canonical dependency schema."""
    return create_dependency_test_db()


def insert_item(conn, item_id, title="", status="idea", worktree=None, merged_at=None):
    if not title:
        title = f"Item {item_id}"
    _now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO items (id, title, status, worktree, merged_at, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (item_id, title, status, worktree, merged_at, _now, _now),
    )


def insert_dep(conn, dependent, blocking,
               gate_point="activation", satisfaction="status:done",
               rationale=""):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, rationale, source, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 'test', '2026-01-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction, rationale),
    )

"""Shared module-level helpers and pytest fixtures for merge_worktree tests.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_merge_worktree.py and its split siblings.

The shared `mw_db` fixture creates the DB schema used by all merge_worktree
tests; consolidating here avoids 4x duplication.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def mw_db(tmp_path):
    """Create a minimal DB for merge-worktree engine tests."""
    from runtime.api.fixtures.file_test_db import (
        apply_fixture_schema_ddl,
        connect_test_db,
        init_test_db,
    )

    config_path = tmp_path / "config"
    config_path.write_text("base_branch=main\nmerge_conflict_threshold=2\n")

    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            for table in (
                "merge_locks", "epic_tasks", "deployment_run_items", "events",
                "items", "projects",
            ):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass
            conn.commit()
            yield {
                "db_path": db_path,
                "conn": conn,
                "tmp_path": tmp_path,
                "config_path": config_path,
            }
        finally:
            conn.close()

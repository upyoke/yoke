"""Parity tests — item-get, item-row, and item-progress CLI commands."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.parity_db_router_test_fixtures import (  # noqa: F401
    _LARGE_SPEC_TEXT,
    item_query_env,
)
from runtime.api.test_parity import _run_db_router


class TestItemGetCLI:
    """Verify item-get CLI command."""

    def test_get_existing_item_status(self, item_query_env):
        """item-get <id> status returns the status value."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-1", "status")
        assert result.returncode == 0
        assert result.stdout.strip() == "implementing"

    def test_get_nonexistent_item(self, item_query_env):
        """item-get YOK-999999 status exits 1 (not found)."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-999999", "status")
        assert result.returncode == 1

    def test_get_empty_field_on_existing_item(self, item_query_env):
        """item-get for empty field on existing item exits 0."""
        db_path = item_query_env["db_path"]
        # Item 2 has no spec
        result = _run_db_router(db_path, "item-get", "YOK-2", "spec")
        assert result.returncode == 0
        # stdout should be empty (field is null)
        assert result.stdout == ""

    def test_get_large_text_field(self, item_query_env):
        """item-get for a large text field returns full content without truncation."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-1", "technical_plan")
        assert result.returncode == 0
        # Verify the content matches
        assert result.stdout == _LARGE_SPEC_TEXT

    def test_get_spec_field(self, item_query_env):
        """item-get for spec field returns content."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-1", "spec")
        assert result.returncode == 0
        assert result.stdout.strip() == "Spec content here"

    def test_get_invalid_field(self, item_query_env):
        """item-get with invalid field exits 2."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-1", "bogus_field")
        assert result.returncode == 2

    def test_get_missing_args(self, item_query_env):
        """item-get with missing arguments exits 2."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "YOK-1")
        assert result.returncode == 2

    def test_get_plain_integer_id(self, item_query_env):
        """item-get accepts plain integer IDs."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-get", "1", "status")
        assert result.returncode == 0
        assert result.stdout.strip() == "implementing"


class TestItemRowCLI:
    """Verify item-row CLI command."""

    def test_row_existing_item(self, item_query_env):
        """item-row <id> returns the full canonical pipe-delimited row."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-row", "YOK-1")
        assert result.returncode == 0
        parts = result.stdout.strip().split("|")
        assert len(parts) == 19  # canonical item row shape from query_item_row()
        assert parts[0] == "1"
        assert parts[1] == "Implementing item"
        assert parts[2] == "issue"
        assert parts[3] == "implementing"
        assert parts[4] == "high"
        assert parts[5] == "accelerated"
        assert parts[15] == "user"
        assert parts[16] == "yoke"

    def test_row_nonexistent_item(self, item_query_env):
        """item-row YOK-999999 exits 1."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-row", "YOK-999999")
        assert result.returncode == 1

    def test_row_missing_args(self, item_query_env):
        """item-row with no args exits 2."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-row")
        assert result.returncode == 2


class TestItemProgressCLI:
    """Verify item-progress CLI command."""

    def test_progress_with_active_run(self, item_query_env):
        """item-progress for item with deployment run returns progress fields."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-progress", "YOK-6")
        assert result.returncode == 0
        parts = result.stdout.strip().split("|")
        assert len(parts) == 9  # 9 progress fields
        assert parts[0] == "release"  # status
        assert parts[1] == "TestFlow"  # flow_name
        assert parts[2] == "run-001"  # run_id
        assert parts[3] == "prod-deploy"  # current_stage

    def test_progress_item_not_in_view(self, item_query_env):
        """item-progress for item without deployment run exits 1 if not in view."""
        db_path = item_query_env["db_path"]
        # Item 2 has no deployment info -- it should still appear in the LEFT JOIN view
        result = _run_db_router(db_path, "item-progress", "YOK-2")
        assert result.returncode == 0  # View uses LEFT JOIN, item exists

    def test_progress_nonexistent_item(self, item_query_env):
        """item-progress for nonexistent item exits 1."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-progress", "YOK-999999")
        assert result.returncode == 1

    def test_progress_missing_view(self, item_query_env):
        """item-progress exits 0 with empty output when view doesn't exist."""
        def _no_view_schema() -> None:
            conn = db_backend.connect()
            conn.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, "
                "slug TEXT UNIQUE NOT NULL, name TEXT, "
                "public_item_prefix TEXT DEFAULT 'YOK')"
            )
            conn.execute(
                "INSERT INTO projects (id, slug, name, public_item_prefix) "
                "VALUES (1, 'yoke', 'Yoke', 'YOK')"
            )
            conn.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, "
                "type TEXT DEFAULT 'issue', status TEXT DEFAULT 'idea', "
                "priority TEXT DEFAULT 'medium', created_at TEXT, "
                "updated_at TEXT, source TEXT DEFAULT '2', "
                "project_id INTEGER DEFAULT 1, project_sequence INTEGER)"
            )
            conn.execute(
                "INSERT INTO items "
                "(id, title, created_at, updated_at, project_id, project_sequence) "
                "VALUES (1, 'Test', '2026-01-01', '2026-01-01', 1, 1)"
            )
            conn.commit()
            conn.close()

        # A separate per-test DB built WITHOUT item_progress_view.
        tmp_dir = tempfile.mkdtemp(prefix="yoke-no-view-")
        try:
            with init_test_db(Path(tmp_dir), apply_schema=_no_view_schema) as db_path:
                result = _run_db_router(db_path, "item-progress", "YOK-1")
                assert result.returncode == 0
                assert result.stdout.strip() == ""
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_progress_missing_args(self, item_query_env):
        """item-progress with no args exits 2."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-progress")
        assert result.returncode == 2

"""Parity tests — item-list and item-count CLI commands."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.parity_db_router_test_fixtures import (  # noqa: F401
    item_query_env,
)
from runtime.api.test_parity import _run_db_router


class TestItemListCLI:
    """Verify item-list CLI command."""

    def test_list_with_status_filter(self, item_query_env):
        """item-list --status idea produces pipe-delimited rows for idea items."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-list", "--status", "idea")
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 2  # items 2 and 3 are idea
        for line in lines:
            parts = line.split("|")
            assert len(parts) == 6  # default fields: id,title,status,priority,type,source
            assert parts[2] == "idea"

    def test_list_with_project_filter(self, item_query_env):
        """item-list --project externalwebapp returns only externalwebapp items."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(
            db_path, "item-list", "--project", "externalwebapp", "--fields", "id,title,project"
        )
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1
        assert "externalwebapp" in lines[0]

    def test_list_custom_fields(self, item_query_env):
        """item-list with custom --fields returns requested columns."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(
            db_path, "item-list", "--status", "implementing", "--fields", "id,status,project"
        )
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1
        parts = lines[0].split("|")
        assert len(parts) == 3
        assert parts[0] == "1"
        assert parts[1] == "implementing"
        assert parts[2] == "yoke"

    def test_list_empty_result(self, item_query_env):
        """item-list with no matching items exits 1."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(
            db_path, "item-list", "--status", "nonexistent-status"
        )
        assert result.returncode == 1

    def test_list_invalid_field(self, item_query_env):
        """item-list with invalid field exits 2."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(
            db_path, "item-list", "--fields", "id,bogus_field"
        )
        assert result.returncode == 2

    def test_list_matches_api_active_queue(self, item_query_env):
        """item-list with status filter matches API /v1/items?status=... response count."""
        db_path = item_query_env["db_path"]
        # Count idea items via CLI
        result = _run_db_router(db_path, "item-list", "--status", "idea")
        assert result.returncode == 0
        cli_count = len(result.stdout.strip().split("\n"))

        # Count via item-count
        count_result = _run_db_router(db_path, "item-count", "--status", "idea")
        assert count_result.returncode == 0
        assert int(count_result.stdout.strip()) == cli_count


class TestItemCountCLI:
    """Verify item-count CLI command."""

    def test_count_with_project_filter(self, item_query_env):
        """item-count --project yoke returns correct count."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-count", "--project", "yoke")
        assert result.returncode == 0
        count = int(result.stdout.strip())
        assert count == 5  # items 1, 2, 4, 5, 6 are yoke

    def test_count_zero_exits_one(self, item_query_env):
        """item-count with no matching items outputs 0 and exits 1."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(
            db_path, "item-count", "--status", "nonexistent-status"
        )
        assert result.returncode == 1
        assert result.stdout.strip() == "0"

    def test_count_all_items(self, item_query_env):
        """item-count with no filters returns total count."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-count")
        assert result.returncode == 0
        count = int(result.stdout.strip())
        assert count == 6  # total items in test DB

    def test_count_with_frozen_filter(self, item_query_env):
        """item-count --frozen 1 counts only frozen items."""
        db_path = item_query_env["db_path"]
        result = _run_db_router(db_path, "item-count", "--frozen", "1")
        assert result.returncode == 0
        assert int(result.stdout.strip()) == 1  # only item 5

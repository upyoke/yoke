"""Tests for yoke_core.domain.items — query_items_list and main() CLI dispatch."""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.fixtures.file_test_db import apply_fixture_schema_ddl, init_test_db
from yoke_core.domain.items import (
    CANONICAL_COLUMNS,
    LIST_COLUMNS,
    insert_item,
    main,
    query_item,
    query_items_list,
)


@pytest.fixture
def db_path(tmp_path):
    """Backend-aware temp DB with the full Yoke schema; yields the path token.

    SQLite: a real file under tmp_path. Postgres: a disposable per-test database
    with YOKE_PG_DSN repointed and dropped on teardown, so factory-routed
    code-under-test lands in an isolated DB (no item-id collision on the shared
    ambient DB across tests).
    """
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        yield path


@pytest.fixture
def db_with_item(db_path):
    insert_item(
        item_id=1,
        title="Test item",
        item_type="issue",
        status="idea",
        priority="medium",
        source="user",
        project="yoke",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        db_path=db_path,
    )
    return db_path


class TestQueryItemsList:
    def test_returns_all_items(self, db_with_item):
        insert_item(item_id=2, title="Second", status="idea", db_path=db_with_item)
        result = query_items_list(db_path=db_with_item)
        lines = result.strip().split("\n")
        assert len(lines) == 2

    def test_filter_by_status(self, db_with_item):
        insert_item(
            item_id=2,
            title="Implementing",
            status="implementing",
            db_path=db_with_item,
        )
        result = query_items_list(status="implementing", db_path=db_with_item)
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert "Implementing" in lines[0]

    def test_filter_by_type(self, db_path):
        insert_item(item_id=1, title="Epic", item_type="epic", status="idea", db_path=db_path)
        insert_item(item_id=2, title="Issue", item_type="issue", status="idea", db_path=db_path)
        result = query_items_list(item_type="epic", db_path=db_path)
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert "Epic" in lines[0]

    def test_filter_by_priority(self, db_path):
        insert_item(item_id=1, title="High", priority="high", db_path=db_path)
        insert_item(item_id=2, title="Low", priority="low", db_path=db_path)
        result = query_items_list(priority="high", db_path=db_path)
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert "High" in lines[0]

    def test_list_column_count(self, db_with_item):
        result = query_items_list(db_path=db_with_item)
        first_line = result.strip().split("\n")[0]
        parts = first_line.split("|")
        assert len(parts) == len(LIST_COLUMNS)

    def test_empty_result(self, db_path):
        result = query_items_list(status="implementing", db_path=db_path)
        assert result == ""

    def test_ordered_by_id(self, db_path):
        insert_item(item_id=5, title="Fifth", db_path=db_path)
        insert_item(item_id=3, title="Third", db_path=db_path)
        insert_item(item_id=8, title="Eighth", db_path=db_path)
        result = query_items_list(db_path=db_path)
        lines = result.strip().split("\n")
        ids = [line.split("|")[0] for line in lines]
        assert ids == ["3", "5", "8"]


class TestCLIMain:
    def test_get_subcommand(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["get", "1", "title"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "Test item"

    def test_get_frozen(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["get", "1", "frozen"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "false"

    def test_row_subcommand(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["row", "1"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        parts = out.split("|")
        assert len(parts) == len(CANONICAL_COLUMNS)
        assert parts[0] == "1"

    def test_row_not_found(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = main(["row", "999"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_list_subcommand(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["list"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert "Test item" in out

    def test_list_with_status_filter(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["list", "--status", "idea"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert "Test item" in out

    def test_list_empty(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = main(["list", "--status", "implementing"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == ""

    def test_no_command_returns_2(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = main([])
        assert rc == 2

    def test_insert_subcommand(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = main([
            "insert", "--id", "50", "--title", "CLI insert",
            "--status", "idea", "--type", "issue",
        ])
        assert rc == 0
        assert query_item(50, "title", db_path=db_path) == "CLI insert"

    def test_update_subcommand(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["update", "1", "priority", "high"])
        assert rc == 0
        assert query_item(1, "priority", db_path=db_with_item) == "high"

    def test_update_body_rejected_via_cli(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["update", "1", "body", "nope"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "Raw body writes are no longer supported" in err

    def test_update_multi_subcommand(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["update-multi", "1", "priority=high", "flow=standard"])
        assert rc == 0
        assert query_item(1, "priority", db_path=db_with_item) == "high"
        assert query_item(1, "flow", db_path=db_with_item) == "standard"

    def test_update_multi_bad_pair(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        rc = main(["update-multi", "1", "noequalssign"])
        assert rc == 2

    def test_update_structured_subcommand(self, db_with_item, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        content_file = tmp_path / "spec.md"
        content_file.write_text("# Spec\nLine 1\nLine 2\n")
        rc = main(["update-structured", "1", "spec", "--body-file", str(content_file)])
        assert rc == 0
        assert query_item(1, "spec", db_path=db_with_item) == "# Spec\nLine 1\nLine 2\n"

    def test_update_structured_subcommand_stdin(self, db_with_item, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        monkeypatch.setattr(sys, "stdin", io.StringIO("# Spec\nFrom stdin\n"))
        rc = main(["update-structured", "1", "spec", "--stdin"])
        assert rc == 0
        assert query_item(1, "spec", db_path=db_with_item) == "# Spec\nFrom stdin\n"

    def test_update_structured_subcommand_rejects_both_sources(
        self, db_with_item, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("YOKE_DB", db_with_item)
        content_file = tmp_path / "spec.md"
        content_file.write_text("# Spec\nFrom file\n", encoding="utf-8")
        monkeypatch.setattr(sys, "stdin", io.StringIO("# Spec\nFrom stdin\n"))

        rc = main([
            "update-structured",
            "1",
            "spec",
            "--body-file",
            str(content_file),
            "--stdin",
        ])

        captured = capsys.readouterr()
        assert rc == 2
        data = json.loads(captured.err.strip())
        assert data["success"] is False
        assert "cannot use both --stdin and --body-file" in data["error"]

    def test_update_structured_subcommand_requires_input(
        self, db_with_item, monkeypatch, capsys
    ):
        monkeypatch.setenv("YOKE_DB", db_with_item)

        rc = main(["update-structured", "1", "spec"])

        captured = capsys.readouterr()
        assert rc == 2
        data = json.loads(captured.err.strip())
        assert data["success"] is False
        assert "requires --body-file or --stdin" in data["error"]

    def test_insert_with_body_file_ignored(self, db_path, monkeypatch, tmp_path, capsys):
        """body param is accepted for compat but ignored."""
        monkeypatch.setenv("YOKE_DB", db_path)
        body_file = tmp_path / "body.md"
        body_file.write_text("Body from file")
        rc = main([
            "insert", "--id", "60", "--title", "File body",
            "--body-file", str(body_file),
        ])
        assert rc == 0
        # body is no longer stored — rendered from structured fields
        assert query_item(60, "title", db_path=db_path) == "File body"

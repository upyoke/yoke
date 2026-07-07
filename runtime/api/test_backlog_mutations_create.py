"""Mutation tests — DB helpers and create paths.

Covers:
  - _insert_item, _update_item_field, _update_item_multi DB helpers
  - execute_create: validation, INSERT, session attribution

Shared fixtures and seed helpers are imported from
``backlog_mutations_test_helpers``.
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from runtime.api.backlog_mutations_test_helpers import (
    _item_field,
    _patch_externals,
    _seed_session,
    _session_attribution,
    insert_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog, db_backend
from yoke_core.domain.ticket_intake_provenance import IDEA_INTAKE_ENV


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# DB Helpers (use test_db fixture for in-memory tests)
# ---------------------------------------------------------------------------


class TestInsertItem:
    def test_basic_insert(self, test_db):
        backlog._insert_item(
            test_db, 99, "Test", "issue", "idea", "medium",
            "accelerated", 0, 0, None, None, None,
            "# Test\n", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "user", 1, 99, None,
        )
        p = _p(test_db)
        row = test_db.execute(f"SELECT title FROM items WHERE id={p}", (99,)).fetchone()
        assert row[0] == "Test"

    def test_duplicate_raises(self, test_db):
        insert_item(test_db, id=50)
        with pytest.raises(db_backend.integrity_error_types()):
            backlog._insert_item(
                test_db, 50, "Dup", "issue", "idea", "medium",
                "accelerated", 0, 0, None, None, None,
                "body", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
                "user", 1, 50, None,
            )

    def test_owner_defaults_to_source(self, test_db):
        backlog._insert_item(
            test_db, 101, "Owner-default", "issue", "idea", "medium",
            "accelerated", 0, 0, None, None, None,
            None, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "7", 1, 101, None,
        )
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT source, owner FROM items WHERE id={p}", (101,)
        ).fetchone()
        assert row[0] == "7"
        assert row[1] == "7"

    def test_explicit_owner_overrides_source(self, test_db):
        backlog._insert_item(
            test_db, 102, "Owner-override", "issue", "idea", "medium",
            "accelerated", 0, 0, None, None, None,
            None, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "7", 1, 102, None,
            owner="9",
        )
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT source, owner FROM items WHERE id={p}", (102,)
        ).fetchone()
        assert row[0] == "7"
        assert row[1] == "9"


class TestUpdateItemField:
    def test_update_string_field(self, test_db):
        insert_item(test_db, id=10, title="Old")
        backlog._update_item_field(test_db, 10, "title", "New")
        p = _p(test_db)
        row = test_db.execute(f"SELECT title FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] == "New"

    def test_update_null(self, test_db):
        insert_item(test_db, id=10, worktree="YOK-10")
        backlog._update_item_field(test_db, 10, "worktree", None)
        p = _p(test_db)
        row = test_db.execute(f"SELECT worktree FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] is None

    def test_update_boolean_field(self, test_db):
        insert_item(test_db, id=10)
        backlog._update_item_field(test_db, 10, "frozen", True)
        p = _p(test_db)
        row = test_db.execute(f"SELECT frozen FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] == 1


class TestUpdateItemMulti:
    def test_multi_field_update(self, test_db):
        insert_item(test_db, id=10, status="idea", priority="low")
        backlog._update_item_multi(test_db, 10, {
            "status": "implementing",
            "priority": "high",
        })
        p = _p(test_db)
        row = test_db.execute(f"SELECT status, priority FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] == "implementing"
        assert row[1] == "high"

    def test_multi_with_null(self, test_db):
        insert_item(test_db, id=10, worktree="YOK-10")
        backlog._update_item_multi(test_db, 10, {
            "worktree": None,
            "frozen": False,
        })
        p = _p(test_db)
        row = test_db.execute(f"SELECT worktree, frozen FROM items WHERE id={p}", (10,)).fetchone()
        assert row[0] is None
        assert row[1] == 0


# ---------------------------------------------------------------------------
# execute_create (uses tmp_db for isolated DB)
# ---------------------------------------------------------------------------


class TestExecuteCreate:
    def test_basic_create(self, tmp_db):
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Test item",
                item_type="issue",
                priority="medium",
                project="yoke",
                out=out,
            )
        assert result["success"] is True
        assert "item_id" in result
        assert _item_field(tmp_db, result["item_id"], "title") == "Test item"
        assert _item_field(tmp_db, result["item_id"], "status") == "idea"
        patched["_rebuild_board"].assert_called_once_with(out)

    def test_create_validation_failure(self, tmp_db):
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="",
                item_type="issue",
                out=out,
            )
        assert result["success"] is False

    def test_create_dry_run(self, tmp_db):
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Dry run item",
                item_type="issue",
                dry_run=True,
                out=out,
            )
        assert result["success"] is True
        assert result.get("dry_run") is True
        assert "[DRY-RUN]" in out.getvalue()
        patched["_rebuild_board"].assert_not_called()

    def test_create_sets_session_current_item(self, tmp_db):
        _seed_session(tmp_db)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db, IDEA_INTAKE_ENV: "1"}):
            result = backlog.execute_create(
                title="Attributed item",
                item_type="issue",
                session_id="sess-1",
                out=out,
            )
        assert result["success"] is True
        attribution = _session_attribution(tmp_db)
        assert attribution["current_item_id"] == str(result["item_id"])
        assert attribution["recent_item_id"] is None

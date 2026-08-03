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
from yoke_core.domain.item_entry_surface import ITEM_ENTRY_SURFACE_ENV


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _issue_pin(conn):
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    return resolve_current_workflow_pin(conn, "issue")


# ---------------------------------------------------------------------------
# DB Helpers (use test_db fixture for in-memory tests)
# ---------------------------------------------------------------------------


class TestInsertItem:
    def test_basic_insert(self, test_db):
        workflow_id, workflow_version_id = _issue_pin(test_db)
        backlog._insert_item(
            test_db, 99, "Test", "idea", "medium",
            0, 0, None, None,
            "# Test\n", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "user", 1, 99, None,
            workflow_id=workflow_id, workflow_version_id=workflow_version_id,
        )
        p = _p(test_db)
        row = test_db.execute(f"SELECT title FROM items WHERE id={p}", (99,)).fetchone()
        assert row[0] == "Test"

    def test_duplicate_raises(self, test_db):
        insert_item(test_db, id=50)
        workflow_id, workflow_version_id = _issue_pin(test_db)
        with pytest.raises(db_backend.integrity_error_types()):
            backlog._insert_item(
                test_db, 50, "Dup", "idea", "medium",
                0, 0, None, None,
                "body", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
                "user", 1, 50, None,
                workflow_id=workflow_id, workflow_version_id=workflow_version_id,
            )

    def test_owner_defaults_to_source(self, test_db):
        workflow_id, workflow_version_id = _issue_pin(test_db)
        backlog._insert_item(
            test_db, 101, "Owner-default", "idea", "medium",
            0, 0, None, None,
            None, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "7", 1, 101, None,
            workflow_id=workflow_id, workflow_version_id=workflow_version_id,
        )
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT source, owner FROM items WHERE id={p}", (101,)
        ).fetchone()
        assert row[0] == "7"
        assert row[1] == "7"

    def test_explicit_owner_overrides_source(self, test_db):
        workflow_id, workflow_version_id = _issue_pin(test_db)
        backlog._insert_item(
            test_db, 102, "Owner-override", "idea", "medium",
            0, 0, None, None,
            None, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
            "7", 1, 102, None,
            workflow_id=workflow_id, workflow_version_id=workflow_version_id,
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
        insert_item(test_db, id=10, blocked_reason="waiting")
        backlog._update_item_field(test_db, 10, "blocked_reason", None)
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT blocked_reason FROM items WHERE id={p}", (10,)
        ).fetchone()
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
        insert_item(test_db, id=10, blocked_reason="waiting")
        backlog._update_item_multi(test_db, 10, {
            "blocked_reason": None,
            "frozen": False,
        })
        p = _p(test_db)
        row = test_db.execute(
            f"SELECT blocked_reason, frozen FROM items WHERE id={p}", (10,)
        ).fetchone()
        assert row[0] is None
        assert row[1] == 0


# ---------------------------------------------------------------------------
# execute_create (uses tmp_db for isolated DB)
# ---------------------------------------------------------------------------


class TestExecuteCreate:
    def test_create_requires_workflow(self):
        result = backlog.execute_create(title="Unclassified")
        assert result == {"success": False, "error": "workflow is required"}

    def test_basic_create(self, tmp_db):  # noqa: F811
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="Test item",
                workflow="issue",
                priority="medium",
                project="yoke",
                out=out,
            )
        assert result["success"] is True
        assert "item_id" in result
        assert _item_field(tmp_db, result["item_id"], "title") == "Test item"
        assert _item_field(tmp_db, result["item_id"], "status") == "idea"
        patched["_rebuild_board"].assert_called_once_with(out)

    def test_dash_instruction_does_not_emit_empty_body_warning(self, tmp_db):  # noqa: F811
        out = io.StringIO()
        instruction = "Fix the footer and verify every link."
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="Dash item",
                workflow="dash",
                project="yoke",
                entry_surface="harness_skill",
                instruction=instruction,
                out=out,
            )

        assert result["success"] is True
        assert _item_field(tmp_db, result["item_id"], "spec") == instruction
        assert "created with no body content" not in out.getvalue()

    def test_empty_dash_body_warns_with_registered_structured_field_recipe(self, tmp_db):  # noqa: F811
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="Empty Dash item",
                workflow="dash",
                project="yoke",
                entry_surface="harness_skill",
                out=out,
            )

        assert result["success"] is True
        log = out.getvalue()
        assert "created with no body content" in log
        assert (
            f"yoke items structured-field replace {result['item_ref']} "
            "--field spec --stdin"
        ) in log
        assert "python3 -m yoke_core.cli.db_router" not in log

    def test_create_validation_failure(self, tmp_db):  # noqa: F811
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="",
                workflow="issue",
                out=out,
            )
        assert result["success"] is False

    def test_create_dry_run(self, tmp_db):  # noqa: F811
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="Dry run item",
                workflow="issue",
                dry_run=True,
                out=out,
            )
        assert result["success"] is True
        assert result.get("dry_run") is True
        assert "[DRY-RUN]" in out.getvalue()
        patched["_rebuild_board"].assert_not_called()

    def test_create_sets_session_current_item(self, tmp_db):  # noqa: F811
        _seed_session(tmp_db)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, ITEM_ENTRY_SURFACE_ENV: "harness_skill"},
             ):
            result = backlog.execute_create(
                title="Attributed item",
                workflow="issue",
                session_id="sess-1",
                out=out,
            )
        assert result["success"] is True
        attribution = _session_attribution(tmp_db)
        assert attribution["current_item_id"] == str(result["item_id"])
        assert attribution["recent_item_id"] is None

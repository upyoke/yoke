"""Comprehensive pytest suite for yoke_core.domain.deployment_runs.

Covers core commands: init, next-id, create-run, add-item, remove-item,
get, update.

Sibling modules cover related surfaces:

- ``test_deployment_runs_full_queries.py`` — list, items, find-by-item, lineage, qa.
- ``test_deployment_runs_full_validation.py`` — validate-composition, batch compatibility.
- ``test_deployment_runs_full_preview.py`` — preview env claim/release/occupancy + cancellation.

The shared fixture ``db_path`` is provided by
``test_deployment_runs_full_helpers.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.schema_common import _get_tables
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    _placeholder,
    db_path,
)


class TestInit:
    """cmd_init idempotency."""

    def test_init_creates_tables(self, db_path):
        conn = _conn(db_path)
        tables = set(_get_tables(conn))
        conn.close()
        assert "deployment_runs" in tables
        assert "deployment_run_items" in tables
        assert "deployment_run_qa" in tables
        assert "deployment_preview_environments" in tables

    def test_init_idempotent(self, db_path):
        # calling init again should not raise
        dr.cmd_init(db_path=db_path)


class TestNextId:
    """cmd_next_id date-based sequence."""

    def test_first_id_ends_with_001(self, db_path):
        rid = dr.cmd_next_id(db_path=db_path)
        assert rid.startswith("run-")
        assert rid.endswith("-001")

    def test_sequential_ids(self, db_path):
        dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        rid2 = dr.cmd_next_id(db_path=db_path)
        assert rid2.endswith("-002")


class TestCreateRun:
    """cmd_create_run with various parameters."""

    def test_basic_create(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        assert rid.startswith("run-")

        result = dr.cmd_get(rid, db_path=db_path)
        assert result is not None
        fields = result.split("|")
        assert fields[1] == "yoke"
        assert fields[5] == "created"

    def test_create_with_target_env(self, db_path):
        rid = dr.cmd_create_run(
            "yoke", "yoke-internal",
            target_env="production",
            db_path=db_path,
        )
        val = dr.cmd_get(rid, field="target_env", db_path=db_path)
        assert val == "production"

    def test_create_with_lineage(self, db_path):
        rid = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-001",
            db_path=db_path,
        )
        val = dr.cmd_get(rid, field="release_lineage", db_path=db_path)
        assert val == "rel-001"

    def test_create_with_created_by(self, db_path):
        rid = dr.cmd_create_run(
            "yoke", "yoke-internal",
            created_by="system",
            db_path=db_path,
        )
        val = dr.cmd_get(rid, field="created_by", db_path=db_path)
        assert val == "system"

    def test_disabled_flow_cannot_start_a_new_run(self, db_path):
        from runtime.api.fixtures.file_test_db import connect_test_db

        with connect_test_db(db_path) as conn:
            conn.execute(
                "UPDATE deployment_flows SET status='disabled' "
                "WHERE id='yoke-internal'"
            )
            conn.commit()
        with pytest.raises(ValueError, match="disabled"):
            dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)

    def test_create_resolves_flow_target_env(self, db_path):
        """When no target_env is given, should resolve from flow's target_env."""
        rid = dr.cmd_create_run("buzz", "buzz-standard", db_path=db_path)
        val = dr.cmd_get(rid, field="target_env", db_path=db_path)
        assert val == "preview"


class TestAddRemoveItem:
    """cmd_add_item and cmd_remove_item."""

    def test_add_item(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        msg = dr.cmd_add_item(rid, 100, db_path=db_path)
        assert "100" in msg

        items_out = dr.cmd_items(rid, db_path=db_path)
        assert "100" in items_out

    def test_add_multiple_items(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(rid, 100, db_path=db_path)
        dr.cmd_add_item(rid, 200, db_path=db_path)

        items_out = dr.cmd_items(rid, db_path=db_path)
        lines = items_out.strip().split("\n")
        assert len(lines) == 2

    def test_remove_item(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(rid, 100, db_path=db_path)
        dr.cmd_add_item(rid, 200, db_path=db_path)
        dr.cmd_remove_item(rid, 100, db_path=db_path)

        items_out = dr.cmd_items(rid, db_path=db_path)
        assert "200" in items_out
        assert "100" not in items_out


class TestGet:
    """cmd_get: full row and single field."""

    def test_get_full_row(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        result = dr.cmd_get(rid, db_path=db_path)
        assert result is not None
        assert rid in result

    def test_get_single_field(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        assert dr.cmd_get(rid, field="status", db_path=db_path) == "created"
        assert dr.cmd_get(rid, field="project", db_path=db_path) == "yoke"

    def test_get_not_found(self, db_path):
        assert dr.cmd_get("nonexistent", db_path=db_path) is None

    def test_get_invalid_field(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        with pytest.raises(ValueError, match="invalid field"):
            dr.cmd_get(rid, field="nonexistent_col", db_path=db_path)


class TestUpdate:
    """cmd_update: status transitions, auto-timestamps, validation."""

    def test_update_status_executing(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "status", "executing", db_path=db_path)
        assert err is None
        assert dr.cmd_get(rid, field="status", db_path=db_path) == "executing"

    def test_executing_sets_started_at(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "status", "executing", db_path=db_path)
        conn = _conn(db_path)
        p = _placeholder(conn)
        started = conn.execute(
            f"SELECT started_at FROM deployment_runs WHERE id={p}", (rid,)
        ).fetchone()[0]
        conn.close()
        assert started is not None

    def test_terminal_status_sets_completed_at(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "status", "failed", db_path=db_path)
        conn = _conn(db_path)
        p = _placeholder(conn)
        completed = conn.execute(
            f"SELECT completed_at FROM deployment_runs WHERE id={p}", (rid,)
        ).fetchone()[0]
        conn.close()
        assert completed is not None

    def test_update_current_stage(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "current_stage", "smoke", db_path=db_path)
        assert err is None
        assert dr.cmd_get(rid, field="current_stage", db_path=db_path) == "smoke"

    def test_update_invalid_status(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "status", "bogus", db_path=db_path)
        assert err is not None
        assert "invalid status" in err

    def test_update_non_updatable_field(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        err = dr.cmd_update(rid, "id", "new-id", db_path=db_path)
        assert err is not None
        assert "not updatable" in err

    def test_update_not_found(self, db_path):
        err = dr.cmd_update("nonexistent", "status", "executing", db_path=db_path)
        assert err is not None
        assert "not found" in err

    def test_succeeded_rejects_failed_stage(self, db_path):
        """status=succeeded rejected if current_stage ends in -failed."""
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "failure" in err.lower() or "failed" in err.lower()

    def test_succeeded_rejects_non_final_stage(self, db_path):
        """status=succeeded rejected if not on final flow stage."""
        rid = dr.cmd_create_run("buzz", "buzz-standard", db_path=db_path)
        dr.cmd_update(rid, "current_stage", "preview", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "not the final stage" in err

    def test_succeeded_accepts_final_stage(self, db_path):
        """status=succeeded accepted when on final stage."""
        rid = dr.cmd_create_run("buzz", "buzz-standard", db_path=db_path)
        dr.cmd_update(rid, "current_stage", "production", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
        assert err is None

    def test_succeeded_force_overrides_guard(self, db_path):
        """force=True bypasses the stage guard."""
        rid = dr.cmd_create_run("buzz", "buzz-standard", db_path=db_path)
        dr.cmd_update(rid, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(rid, "status", "succeeded", force=True, db_path=db_path)
        assert err is None

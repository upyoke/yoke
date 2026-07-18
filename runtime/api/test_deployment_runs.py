# ruff: noqa: F811
"""Tests for yoke_core.domain.deployment_runs — core CRUD path.
Covers init, ID generation, run creation, item add/remove, get/update/list,
and find-by-item. Lineage, QA, validation, CLI exit codes, preview
environments, and cleanup live in sibling test modules:

- ``test_deployment_runs_lineage_qa.py`` — lineage, QA, validation, CLI.
- ``test_deployment_runs_preview.py`` — preview claim/release lifecycle and cleanup.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.schema_common import _get_tables
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401, F811 — fixture re-export
from runtime.api.fixtures.file_test_db import connect_test_db


class TestInit:
    def test_init_creates_tables(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        tables = _get_tables(conn)
        conn.close()
        assert "deployment_runs" in tables
        assert "deployment_run_items" in tables
        assert "deployment_run_qa" in tables
        assert "deployment_preview_environments" in tables

    def test_init_is_idempotent(self, db_path: str) -> None:
        # Running init again should not fail
        dr.cmd_init(db_path=db_path)


class TestNextIdAndCreateRun:
    def test_next_id_format(self, db_path: str) -> None:
        run_id = dr.cmd_next_id(db_path=db_path)
        assert run_id.startswith("run-")
        assert run_id.endswith("-001")

    def test_next_id_increments(self, db_path: str) -> None:
        # Create a run to consume 001
        dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        run_id = dr.cmd_next_id(db_path=db_path)
        assert run_id.endswith("-002")

    def test_create_run_returns_id(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        assert run_id.startswith("run-")

    def test_create_run_resolves_target_env_from_flow(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        result = dr.cmd_get(run_id, field="target_env", db_path=db_path)
        assert result == "production"

    def test_create_run_with_explicit_target_env(self, db_path: str) -> None:
        run_id = dr.cmd_create_run(
            "yoke", "flow-main", target_env="staging", db_path=db_path
        )
        result = dr.cmd_get(run_id, field="target_env", db_path=db_path)
        assert result == "staging"

    def test_create_run_with_lineage(self, db_path: str) -> None:
        run_id = dr.cmd_create_run(
            "yoke", "flow-main", release_lineage="lin-001", db_path=db_path
        )
        result = dr.cmd_get(run_id, field="release_lineage", db_path=db_path)
        assert result == "lin-001"

    def test_create_run_custom_created_by(self, db_path: str) -> None:
        run_id = dr.cmd_create_run(
            "yoke", "flow-main", created_by="tester", db_path=db_path
        )
        result = dr.cmd_get(run_id, field="created_by", db_path=db_path)
        assert result == "tester"


class TestItemManagement:
    def test_add_and_list_items(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        # Insert test items
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (100, 'Test', 'implemented', 1, 100)")
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (101, 'Test2', 'implemented', 1, 101)")
        conn.commit()
        conn.close()

        dr.cmd_add_item(run_id, 100, db_path=db_path)
        dr.cmd_add_item(run_id, 101, db_path=db_path)

        result = dr.cmd_items(run_id, db_path=db_path)
        assert "100" in result
        assert "101" in result

    def test_remove_item(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (200, 'Test', 'implemented', 1, 200)")
        conn.commit()
        conn.close()

        dr.cmd_add_item(run_id, 200, db_path=db_path)
        dr.cmd_remove_item(run_id, 200, db_path=db_path)

        result = dr.cmd_items(run_id, db_path=db_path)
        assert result == ""


class TestGet:
    def test_get_full_row(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        result = dr.cmd_get(run_id, db_path=db_path)
        assert result is not None
        parts = result.split("|")
        assert parts[0] == run_id
        assert parts[1] == "yoke"
        assert parts[2] == "flow-main"
        assert parts[5] == "created"

    def test_get_single_field(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        assert dr.cmd_get(run_id, field="status", db_path=db_path) == "created"

    def test_get_not_found(self, db_path: str) -> None:
        result = dr.cmd_get("nonexistent", db_path=db_path)
        assert result is None

    def test_get_invalid_field(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        with pytest.raises(ValueError, match="invalid field"):
            dr.cmd_get(run_id, field="bogus", db_path=db_path)


class TestUpdate:
    def test_update_status_executing_sets_started_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "executing", db_path=db_path)
        assert err is None
        result = dr.cmd_get(run_id, db_path=db_path)
        parts = result.split("|")
        assert parts[5] == "executing"
        assert parts[8] != ""  # started_at set

    def test_update_status_succeeded_sets_completed_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        # Set current_stage to final stage for guard to pass
        dr.cmd_update(run_id, "current_stage", "complete", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)
        assert err is None
        result = dr.cmd_get(run_id, db_path=db_path)
        parts = result.split("|")
        assert parts[5] == "succeeded"
        assert parts[9] != ""  # completed_at set

    def test_update_status_failed_sets_completed_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "failed", db_path=db_path)
        assert err is None
        assert dr.cmd_get(run_id, field="status", db_path=db_path) == "failed"

    def test_update_invalid_status(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "bogus", db_path=db_path)
        assert err is not None
        assert "invalid status" in err

    def test_update_non_updatable_field(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "id", "new-id", db_path=db_path)
        assert err is not None
        assert "not updatable" in err

    def test_update_not_found(self, db_path: str) -> None:
        err = dr.cmd_update("nonexistent", "status", "executing", db_path=db_path)
        assert err is not None
        assert "not found" in err

    def test_update_succeeded_guard_failed_stage(self, db_path: str) -> None:
        """Reject succeeded if current_stage ends in -failed."""
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "indicates failure" in err

    def test_update_succeeded_guard_force_override(self, db_path: str) -> None:
        """--force bypasses the guard."""
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "deploy-failed", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "succeeded", force=True, db_path=db_path)
        assert err is None

    def test_update_succeeded_guard_wrong_final_stage(self, db_path: str) -> None:
        """Reject if current_stage is not the final flow stage."""
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_update(run_id, "current_stage", "merged", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)
        assert err is not None
        assert "not the final stage" in err


class TestList:
    def test_list_all(self, db_path: str) -> None:
        dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        result = dr.cmd_list(db_path=db_path)
        lines = result.strip().split("\n")
        assert len(lines) == 2

    def test_list_by_project(self, db_path: str) -> None:
        dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        result = dr.cmd_list(project="externalwebapp", db_path=db_path)
        assert result == ""

    def test_list_by_status(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_update(run_id, "status", "executing", db_path=db_path)
        result = dr.cmd_list(status="executing", db_path=db_path)
        assert run_id in result


class TestFindByItem:
    def test_find_by_item(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (300, 'T', 'implemented', 1, 300)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 300, db_path=db_path)

        result = dr.cmd_find_by_item(300, db_path=db_path)
        assert run_id in result

    def test_find_by_item_with_status_filter(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (301, 'T', 'implemented', 1, 301)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 301, db_path=db_path)

        result = dr.cmd_find_by_item(301, status="executing", db_path=db_path)
        assert result == ""  # run is 'created', not 'executing'

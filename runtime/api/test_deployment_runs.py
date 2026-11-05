# ruff: noqa: F811
"""Tests for yoke_core.domain.deployment_runs — core CRUD path.
Covers init, ID generation, run creation, item add/remove, get/update/list,
and find-by-item. Lineage, QA, validation, CLI exit codes, preview
environments, and cleanup live in sibling test modules:

- ``test_deployment_runs_lineage_qa.py`` — lineage, QA, validation, CLI.
- ``test_deployment_runs_full_preview.py`` — preview claim/release lifecycle and cleanup.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_runs_schema import RUN_FIELDS
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401, F811 — fixture re-export
from runtime.api.fixtures.file_test_db import connect_test_db


class TestNextIdAndCreateRun:


    def test_create_run_copies_target_from_flow(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        tier = dr.cmd_get(run_id, field="target_tier", db_path=db_path)
        environment = dr.cmd_get(run_id, field="target_environment", db_path=db_path)
        assert (tier, environment) == ("persistent", "prod")

    def test_create_run_with_environment_override(self, db_path: str) -> None:
        run_id = dr.cmd_create_run(
            "yoke", "flow-main", environment="stage", db_path=db_path
        )
        environment = dr.cmd_get(run_id, field="target_environment", db_path=db_path)
        assert environment == "stage"


class TestItemManagement:

    def test_remove_item(self, db_path: str) -> None:
        from yoke_core.domain.qa_schema import cmd_init
        from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables
        from runtime.api.api_workflow_test_helpers import (
            install_workflow_registry_and_pin_items,
        )

        cmd_init(db_path=db_path)
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (200, 'Test', 'implemented', 1, 200)"
        )
        install_workflow_registry_and_pin_items(conn)
        create_qa_catalog_tables(conn)
        conn.commit()
        conn.close()

        dr.cmd_add_item(run_id, 200, db_path=db_path)
        dr.cmd_remove_item(run_id, 200, reason="test removal", db_path=db_path)

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
        assert parts[6] == "created"


    @pytest.mark.parametrize("field", ["bogus", "stages"])
    def test_get_invalid_field(self, db_path: str, field: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        with pytest.raises(ValueError, match="invalid field") as refusal:
            dr.cmd_get(run_id, field=field, db_path=db_path)
        assert f"Accepted fields: {', '.join(sorted(RUN_FIELDS))}." in str(
            refusal.value
        )
        if field == "stages":
            assert f"yoke deployment-runs stages {run_id}" in str(refusal.value)


class TestUpdate:
    def test_update_status_executing_sets_started_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "executing", db_path=db_path)
        assert err is None
        result = dr.cmd_get(run_id, db_path=db_path)
        parts = result.split("|")
        assert parts[6] == "executing"
        assert parts[9] != ""  # started_at set

    def test_update_status_succeeded_sets_completed_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        # Set current_stage to final stage for guard to pass
        dr.cmd_update(run_id, "current_stage", "complete", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)
        assert err is None
        result = dr.cmd_get(run_id, db_path=db_path)
        parts = result.split("|")
        assert parts[6] == "succeeded"
        assert parts[10] != ""  # completed_at set

    def test_update_status_failed_sets_completed_at(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        err = dr.cmd_update(run_id, "status", "failed", db_path=db_path)
        assert err is None
        assert dr.cmd_get(run_id, field="status", db_path=db_path) == "failed"
        assert dr.cmd_get(run_id, field="completed_at", db_path=db_path)

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


    def test_list_by_status(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_update(run_id, "status", "executing", db_path=db_path)
        result = dr.cmd_list(status="executing", db_path=db_path)
        assert run_id in result


class TestFindByItem:

    def test_find_by_item_with_status_filter(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (301, 'T', 'implemented', 1, 301)"
        )
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 301, db_path=db_path)

        result = dr.cmd_find_by_item(301, status="executing", db_path=db_path)
        assert result == ""  # run is 'created', not 'executing'

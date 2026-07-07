"""Tests for yoke_core.domain.deployment_runs — preview environments and cleanup.

Split from test_deployment_runs.py: TestPreviewEnvironments, TestCanCleanupPreview.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401 — fixture re-export
from runtime.api.fixtures.file_test_db import connect_test_db


class TestPreviewEnvironments:
    def test_preview_check_available(self, db_path: str) -> None:
        result = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert result == "available"

    def test_preview_claim_and_check(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_preview_claim(run_id, "yoke", "preview-1", db_path=db_path)
        result = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert result == "claimed"

    def test_preview_release(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_preview_claim(run_id, "yoke", "preview-1", db_path=db_path)
        dr.cmd_preview_release(run_id, db_path=db_path)
        result = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert result == "available"

    def test_check_preview_occupancy_empty(self, db_path: str) -> None:
        result = dr.cmd_check_preview_occupancy("yoke", "preview-2", db_path=db_path)
        assert result == "empty"

    def test_check_preview_occupancy_active(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (600, 'P', 'implemented', 1, 600)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 600, db_path=db_path)
        dr.cmd_preview_claim(run_id, "yoke", "preview-3", db_path=db_path)

        result = dr.cmd_check_preview_occupancy("yoke", "preview-3", db_path=db_path)
        assert result.startswith("active|")
        assert run_id in result
        assert "YOK-600" in result

    def test_claim_preview_with_event(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        msg = dr.cmd_claim_preview(run_id, "yoke", "prev-1", db_path=db_path)
        assert "Claimed" in msg

    def test_claim_preview_overwrite(self, db_path: str) -> None:
        r1 = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        r2 = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_claim_preview(r1, "yoke", "prev-2", db_path=db_path)
        msg = dr.cmd_claim_preview(r2, "yoke", "prev-2", db_path=db_path)
        assert "Overwritten" in msg

    def test_claim_preview_invalid_env_type(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        with pytest.raises(ValueError):
            dr.cmd_claim_preview(run_id, "yoke", "prev-3", env_type="bogus", db_path=db_path)


class TestCanCleanupPreview:
    def test_no_preview(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(run_id, db_path=db_path)
        assert not allowed
        assert "No preview" in msg

    def test_shared_env_blocked(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_claim_preview(run_id, "yoke", "shared-env", env_type="shared", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(run_id, db_path=db_path)
        assert not allowed
        assert "shared" in msg

    def test_no_lineage_blocked(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_claim_preview(run_id, "yoke", "adhoc-env", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(run_id, db_path=db_path)
        assert not allowed
        assert "no release lineage" in msg

    def test_cleanup_allowed_when_final_succeeded(self, db_path: str) -> None:
        lin = dr.cmd_lineage_create(db_path=db_path)
        r1 = dr.cmd_create_run("yoke", "flow-main", release_lineage=lin, db_path=db_path)
        dr.cmd_claim_preview(r1, "yoke", "cleanup-env", db_path=db_path)

        # Create another run in lineage that succeeds
        r2 = dr.cmd_create_run(
            "yoke", "flow-main", release_lineage=lin,
            target_env="production", db_path=db_path,
        )
        dr.cmd_update(r2, "current_stage", "complete", db_path=db_path)
        dr.cmd_update(r2, "status", "succeeded", db_path=db_path)

        allowed, msg = dr.cmd_can_cleanup_preview(r1, db_path=db_path)
        assert allowed
        assert "succeeded" in msg

    def test_cleanup_blocked_when_final_failed(self, db_path: str) -> None:
        lin = dr.cmd_lineage_create(db_path=db_path)
        r1 = dr.cmd_create_run("yoke", "flow-main", release_lineage=lin, db_path=db_path)
        dr.cmd_claim_preview(r1, "yoke", "fail-env", db_path=db_path)

        r2 = dr.cmd_create_run("yoke", "flow-main", release_lineage=lin, db_path=db_path)
        dr.cmd_update(r2, "status", "failed", db_path=db_path)

        allowed, msg = dr.cmd_can_cleanup_preview(r1, db_path=db_path)
        assert not allowed
        assert "failed" in msg

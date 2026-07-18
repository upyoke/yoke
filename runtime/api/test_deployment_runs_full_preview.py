# ruff: noqa: F811
"""Preview-environment + cancellation tests for deployment_runs.
Covers cmd_preview_check, cmd_preview_claim, cmd_preview_release,
cmd_check_preview_occupancy, cmd_claim_preview, cmd_can_cleanup_preview,
cmd_resolve_target_env, plus terminal cancelled status.

Split from ``test_deployment_runs_full.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    _placeholder,
    db_path,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestPreviewCheck:
    """cmd_preview_check, cmd_preview_claim, cmd_preview_release."""

    def test_check_available_initially(self, db_path):
        status = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert status == "available"

    def test_claim_and_check(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_preview_claim(rid, "yoke", "preview-1", db_path=db_path)
        status = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert status == "claimed"

    def test_release_and_check(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_preview_claim(rid, "yoke", "preview-1", db_path=db_path)
        dr.cmd_preview_release(rid, db_path=db_path)
        status = dr.cmd_preview_check("yoke", "preview-1", db_path=db_path)
        assert status == "available"


class TestCheckPreviewOccupancy:
    """cmd_check_preview_occupancy: structured occupancy check."""

    def test_empty_when_no_record(self, db_path):
        result = dr.cmd_check_preview_occupancy("yoke", "preview-1", db_path=db_path)
        assert result == "empty"

    def test_active_when_claimed(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_preview_claim(rid, "yoke", "preview-1", db_path=db_path)
        result = dr.cmd_check_preview_occupancy("yoke", "preview-1", db_path=db_path)
        assert result.startswith("active|")
        assert rid in result

    def test_empty_after_release(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_preview_claim(rid, "yoke", "preview-1", db_path=db_path)
        dr.cmd_preview_release(rid, db_path=db_path)
        result = dr.cmd_check_preview_occupancy("yoke", "preview-1", db_path=db_path)
        assert result == "empty"

    def test_occupancy_shows_items(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_add_item(rid, TEST_ITEM_ID, db_path=db_path)
        dr.cmd_preview_claim(rid, "yoke", "preview-1", db_path=db_path)
        result = dr.cmd_check_preview_occupancy("yoke", "preview-1", db_path=db_path)
        assert TEST_ITEM_REF in result


class TestClaimPreview:
    """cmd_claim_preview: claim with env_type and overwrite detection."""

    def test_claim_adhoc(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        msg = dr.cmd_claim_preview(rid, "yoke", "preview-1", "adhoc", db_path=db_path)
        assert "Claimed" in msg

    def test_claim_shared(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        msg = dr.cmd_claim_preview(rid, "yoke", "preview-1", "shared", db_path=db_path)
        assert "Claimed" in msg

    def test_invalid_env_type(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        with pytest.raises(ValueError, match="shared.*adhoc"):
            dr.cmd_claim_preview(rid, "yoke", "preview-1", "bogus", db_path=db_path)

    def test_overwrite_claim(self, db_path):
        r1 = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        r2 = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_claim_preview(r1, "yoke", "preview-1", "adhoc", db_path=db_path)
        msg = dr.cmd_claim_preview(r2, "yoke", "preview-1", "adhoc", db_path=db_path)
        assert "Overwritten" in msg


class TestCanCleanupPreview:
    """cmd_can_cleanup_preview: cleanup rules."""

    def test_no_preview_env(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(rid, db_path=db_path)
        assert allowed is False
        assert "No preview" in msg

    def test_shared_env_blocked(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_claim_preview(rid, "yoke", "preview-1", "shared", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(rid, db_path=db_path)
        assert allowed is False
        assert "shared" in msg

    def test_adhoc_no_lineage_blocked(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_claim_preview(rid, "yoke", "preview-1", "adhoc", db_path=db_path)
        allowed, msg = dr.cmd_can_cleanup_preview(rid, db_path=db_path)
        assert allowed is False
        assert "no release lineage" in msg

    def test_adhoc_lineage_succeeded_allowed(self, db_path):
        r1 = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-cleanup", db_path=db_path,
        )
        dr.cmd_claim_preview(r1, "yoke", "preview-1", "adhoc", db_path=db_path)

        # Create another run in the same lineage that succeeded
        r2 = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-cleanup", db_path=db_path,
        )
        dr.cmd_update(r2, "status", "succeeded", db_path=db_path)

        allowed, msg = dr.cmd_can_cleanup_preview(r1, db_path=db_path)
        assert allowed is True
        assert "succeeded" in msg

    def test_adhoc_lineage_failed_blocked(self, db_path):
        r1 = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-cleanup2", db_path=db_path,
        )
        dr.cmd_claim_preview(r1, "yoke", "preview-1", "adhoc", db_path=db_path)

        r2 = dr.cmd_create_run(
            "yoke", "yoke-internal",
            release_lineage="rel-cleanup2", db_path=db_path,
        )
        dr.cmd_update(r2, "status", "failed", db_path=db_path)

        allowed, msg = dr.cmd_can_cleanup_preview(r1, db_path=db_path)
        assert allowed is False
        assert "failed" in msg


class TestResolveTargetEnv:
    """cmd_resolve_target_env: override vs flow default."""

    def test_override_takes_priority(self, db_path):
        result = dr.cmd_resolve_target_env(
            "externalwebapp", "externalwebapp-standard",
            target_env_override="staging",
            db_path=db_path,
        )
        assert result == "staging"

    def test_flow_default(self, db_path):
        result = dr.cmd_resolve_target_env("externalwebapp", "externalwebapp-standard", db_path=db_path)
        assert result == "preview"

    def test_no_default_returns_empty(self, db_path):
        result = dr.cmd_resolve_target_env(
            "yoke", "yoke-internal", db_path=db_path,
        )
        assert result == ""


class TestCancelledStatus:
    """Terminal status cancelled sets completed_at."""

    def test_cancelled_sets_completed_at(self, db_path):
        rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
        dr.cmd_update(rid, "status", "cancelled", db_path=db_path)
        conn = _conn(db_path)
        p = _placeholder(conn)
        completed = conn.execute(
            f"SELECT completed_at FROM deployment_runs WHERE id={p}", (rid,)
        ).fetchone()[0]
        conn.close()
        assert completed is not None
        assert dr.cmd_get(rid, field="status", db_path=db_path) == "cancelled"

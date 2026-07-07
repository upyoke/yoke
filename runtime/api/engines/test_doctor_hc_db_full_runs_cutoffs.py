"""Cutoff tests for HC-incomplete-deploy-stage (YOK-1704 task 3).

Sibling of test_doctor_hc_db_full.py (>=300 lines). The parent file is
at-cap; cutoff regressions live here so the parent does not grow.

Cutoff key: hc_incomplete_deploy_stage_min_item_id (read from
machine config via yoke_core.engines.doctor_report._read_int_cutoff).
A row whose item_id is below the cutoff is excluded from the WARN
roll-up; a row at or above the cutoff is still flagged.
"""

from __future__ import annotations

from runtime.api.conftest import insert_item
from yoke_core.engines._doctor_hc_cutoff_test_helpers import (
    _patch_repo_root,
    _write_cutoff,
)
from yoke_core.engines._doctor_hc_db_full_test_helpers import (
    _result,
    _run_hc,
)
from yoke_core.engines.doctor import hc_incomplete_deploy_stage

_CUTOFF_KEY = "hc_incomplete_deploy_stage_min_item_id"


def _seed_done_with_incomplete_stage(conn, item_id: int) -> None:
    """Insert a done item that trips HC-incomplete-deploy-stage."""
    insert_item(
        conn,
        id=item_id,
        title=f"Done item {item_id} with no deploy_stage",
        status="done",
        deployment_flow="full",
        deploy_stage=None,
    )


class TestIncompleteDeployStageCutoff:
    def test_row_below_cutoff_excluded(self, test_db, tmp_path):
        """Item id below cutoff is suppressed; PASS when only that row exists."""
        _seed_done_with_incomplete_stage(test_db, item_id=100)
        _write_cutoff(tmp_path, _CUTOFF_KEY, 1700)

        with _patch_repo_root(tmp_path):
            rec = _run_hc(hc_incomplete_deploy_stage, test_db)

        result = _result(rec)
        assert result.result == "PASS"
        assert "YOK-100" not in result.detail

    def test_row_above_cutoff_flagged(self, test_db, tmp_path):
        """Item id at/above cutoff still trips the WARN."""
        _seed_done_with_incomplete_stage(test_db, item_id=1700)
        _write_cutoff(tmp_path, _CUTOFF_KEY, 1700)

        with _patch_repo_root(tmp_path):
            rec = _run_hc(hc_incomplete_deploy_stage, test_db)

        result = _result(rec)
        assert result.result == "WARN"
        assert "YOK-1700" in result.detail

    def test_no_cutoff_keeps_legacy_behavior(self, test_db, tmp_path):
        """Absent cutoff key preserves the pre-cutoff WARN on all rows."""
        _seed_done_with_incomplete_stage(test_db, item_id=100)
        # tmp_path has no configured cutoff
        with _patch_repo_root(tmp_path):
            rec = _run_hc(hc_incomplete_deploy_stage, test_db)

        result = _result(rec)
        assert result.result == "WARN"
        assert "YOK-100" in result.detail

    def test_cutoff_partitions_mixed_rows(self, test_db, tmp_path):
        """Mixed below/above set: only above-cutoff rows appear in detail."""
        _seed_done_with_incomplete_stage(test_db, item_id=100)
        _seed_done_with_incomplete_stage(test_db, item_id=1701)
        _write_cutoff(tmp_path, _CUTOFF_KEY, 1700)

        with _patch_repo_root(tmp_path):
            rec = _run_hc(hc_incomplete_deploy_stage, test_db)

        result = _result(rec)
        assert result.result == "WARN"
        assert "YOK-100" not in result.detail
        assert "YOK-1701" in result.detail

"""SML coherence and SchedulerResult shape tests for yoke_core.domain.scheduler."""
from __future__ import annotations

import os
from unittest.mock import patch

from yoke_core.domain.scheduler import (
    _compute_sml_state,
    compute_schedule,
)

# Re-export the fixture so pytest discovers it in this module.
from runtime.api.scheduler_test_fixtures import (  # noqa: F401
    scheduler_db,
)


class TestSMLState:
    """Verify truthful SML computation."""

    def test_all_files_exist_coherent(self, scheduler_db):
        """When all 4 SML files exist, coherent=True."""
        tmp_dir = scheduler_db["tmp_dir"]
        strategy_dir = os.path.join(tmp_dir, ".yoke", "strategy")
        os.makedirs(strategy_dir, exist_ok=True)
        for fname in ("MISSION.md", "LANDSCAPE.md", "VISION.md", "MASTER-PLAN.md"):
            with open(os.path.join(strategy_dir, fname), "w") as f:
                f.write(f"# {fname}\n")
                # Make mtime far in the future so not stale
                os.utime(os.path.join(strategy_dir, fname), (9999999999, 9999999999))

        sml = _compute_sml_state(scheduler_db["conn"], "yoke", workspace=tmp_dir)
        assert sml.coherent is True

    def test_missing_files_incoherent(self, scheduler_db):
        """When SML files are missing, coherent=False."""
        sml = _compute_sml_state(scheduler_db["conn"], "yoke", workspace=scheduler_db["tmp_dir"])
        assert sml.coherent is False

    def test_partial_files_incoherent(self, scheduler_db):
        """When only some SML files exist, coherent=False."""
        tmp_dir = scheduler_db["tmp_dir"]
        strategy_dir = os.path.join(tmp_dir, ".yoke", "strategy")
        os.makedirs(strategy_dir, exist_ok=True)
        with open(os.path.join(strategy_dir, "VISION.md"), "w") as f:
            f.write("# Vision\n")

        sml = _compute_sml_state(scheduler_db["conn"], "yoke", workspace=tmp_dir)
        assert sml.coherent is False


class TestSchedulerResultShape:
    """Verify SchedulerResult contract after payoff-model removals."""

    def test_schedule_result_no_graph_stale(self, scheduler_db):
        """SchedulerResult no longer carries graph_stale."""
        conn = scheduler_db["conn"]
        result = compute_schedule(conn, project_scope=["yoke"])
        assert not hasattr(result, "graph_stale")

    @patch("yoke_core.domain.scheduler._emit_frontier_step_selected")
    def test_schedule_still_emits_frontier_step_selected(self, mock_emit, scheduler_db):
        """FrontierStepSelected emission survives the graph_stale removal."""
        conn = scheduler_db["conn"]
        result = compute_schedule(conn, project_scope=["yoke"])
        mock_emit.assert_called_once_with(conn, result, None)

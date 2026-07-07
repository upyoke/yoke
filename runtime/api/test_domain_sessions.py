"""Tests for yoke_core.domain.runs — RunStatus enum, active-run lookup,
stage advancement, and SQL fragment helpers.

Query-related tests live in ``test_domain_sessions_queries.py``;
status-to-bucket mapping lives in ``test_domain_sessions_board_bucket.py``;
board projection lives in ``test_domain_sessions_board_projection.py``.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.runs import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    DeploymentRun,
    RunStatus,
    advance_run_stage,
    find_active_run_for_item,
    is_active_run,
    is_terminal_run,
    is_valid_run_status,
    item_has_active_run,
    sql_active_run_exists_for_item,
    sql_active_run_statuses,
    sql_terminal_run_statuses,
)


# ===========================================================================
# Deployment Runs — RunStatus enum
# ===========================================================================


class TestRunStatus:
    """Test run status enum values and membership checks."""

    def test_all_run_statuses_present(self):
        expected = {"created", "executing", "succeeded", "failed", "cancelled"}
        actual = {s.value for s in RunStatus}
        assert actual == expected

    def test_active_run_statuses(self):
        assert ACTIVE_RUN_STATUSES == frozenset({"created", "executing"})

    def test_terminal_run_statuses(self):
        assert TERMINAL_RUN_STATUSES == frozenset({"succeeded", "failed", "cancelled"})

    def test_is_valid_run_status(self):
        for s in ("created", "executing", "succeeded", "failed", "cancelled"):
            assert is_valid_run_status(s) is True
        assert is_valid_run_status("active") is False
        assert is_valid_run_status("done") is False
        assert is_valid_run_status("") is False

    def test_is_active_run(self):
        assert is_active_run("created") is True
        assert is_active_run("executing") is True
        assert is_active_run("succeeded") is False
        assert is_active_run("failed") is False
        assert is_active_run("cancelled") is False

    def test_is_terminal_run(self):
        assert is_terminal_run("succeeded") is True
        assert is_terminal_run("failed") is True
        assert is_terminal_run("cancelled") is True
        assert is_terminal_run("created") is False
        assert is_terminal_run("executing") is False


# ===========================================================================
# Deployment Runs — Active-run lookup
# ===========================================================================


def _make_run(
    run_id: str = "run-1",
    status: str = "executing",
    current_stage: str | None = "build",
    **kwargs,
) -> DeploymentRun:
    """Factory for test DeploymentRun objects."""
    return DeploymentRun(
        id=run_id,
        project="yoke",
        flow="test-flow",
        status=status,
        current_stage=current_stage,
        **kwargs,
    )


class TestFindActiveRun:
    """Test active-run lookup for items."""

    def test_find_active_executing_run(self):
        runs = [
            _make_run("run-2", "executing", "deploy"),
            _make_run("run-1", "succeeded", "complete"),
        ]
        result = find_active_run_for_item(runs)
        assert result is not None
        assert result.id == "run-2"

    def test_find_active_created_run(self):
        runs = [_make_run("run-1", "created", None)]
        result = find_active_run_for_item(runs)
        assert result is not None
        assert result.id == "run-1"

    def test_no_active_run_when_all_terminal(self):
        runs = [
            _make_run("run-2", "failed"),
            _make_run("run-1", "succeeded"),
        ]
        result = find_active_run_for_item(runs)
        assert result is None

    def test_no_active_run_when_empty(self):
        result = find_active_run_for_item([])
        assert result is None

    def test_item_has_active_run_true(self):
        runs = [_make_run("run-1", "executing")]
        assert item_has_active_run(runs) is True

    def test_item_has_active_run_false(self):
        runs = [_make_run("run-1", "succeeded")]
        assert item_has_active_run(runs) is False


# ===========================================================================
# Deployment Runs — Stage advancement
# ===========================================================================


class TestStageAdvancement:
    """Test deployment-run stage advancement logic."""

    def test_advance_to_next_stage(self):
        run = _make_run(current_stage="build")
        result = advance_run_stage(run, ["build", "test", "deploy"])
        assert result.advanced is True
        assert result.next_stage == "test"
        assert result.run_id == run.id
        assert result.error is None

    def test_advance_to_complete(self):
        run = _make_run(current_stage="deploy")
        result = advance_run_stage(run, ["build", "test", "deploy"])
        assert result.advanced is True
        assert result.next_stage == "complete"

    def test_advance_from_no_stage_to_first(self):
        run = _make_run(current_stage=None)
        result = advance_run_stage(run, ["build", "test"])
        assert result.advanced is True
        assert result.next_stage == "build"

    def test_advance_from_no_stage_empty_flow(self):
        run = _make_run(current_stage=None)
        result = advance_run_stage(run, [])
        assert result.advanced is False
        assert "no stages" in result.error

    def test_advance_terminal_run_rejected(self):
        run = _make_run(status="succeeded")
        result = advance_run_stage(run, ["build", "test"])
        assert result.advanced is False
        assert "terminal status" in result.error

    def test_advance_failed_run_rejected(self):
        run = _make_run(status="failed")
        result = advance_run_stage(run, ["build", "test"])
        assert result.advanced is False
        assert "terminal status" in result.error

    def test_advance_cancelled_run_rejected(self):
        run = _make_run(status="cancelled")
        result = advance_run_stage(run, ["build"])
        assert result.advanced is False
        assert "terminal status" in result.error

    def test_advance_unknown_stage_rejected(self):
        run = _make_run(current_stage="nonexistent")
        result = advance_run_stage(run, ["build", "test"])
        assert result.advanced is False
        assert "does not match" in result.error

    def test_advance_single_stage_flow(self):
        run = _make_run(current_stage="deploy")
        result = advance_run_stage(run, ["deploy"])
        assert result.advanced is True
        assert result.next_stage == "complete"


# ===========================================================================
# Deployment Runs — SQL fragment helpers
# ===========================================================================


class TestRunSqlHelpers:
    """Test SQL fragment helpers for run filtering."""

    def test_sql_active_run_statuses(self):
        frag = sql_active_run_statuses()
        assert "'created'" in frag
        assert "'executing'" in frag

    def test_sql_terminal_run_statuses(self):
        frag = sql_terminal_run_statuses()
        assert "'succeeded'" in frag
        assert "'failed'" in frag
        assert "'cancelled'" in frag

    def test_sql_active_run_exists_default_col(self):
        frag = sql_active_run_exists_for_item()
        assert "i.id" in frag
        assert "deployment_run_items" in frag
        assert "deployment_runs" in frag
        assert "'executing'" in frag

    def test_sql_active_run_exists_custom_col(self):
        frag = sql_active_run_exists_for_item("items.id")
        assert "items.id" in frag

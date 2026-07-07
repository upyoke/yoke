"""Tests for the done-transition Python engine: gates and CLI parsing.

Transition mechanics live in test_done_transition.py.
Post-transition (cleanup, cascade, merge) tests live in test_done_transition_post.py.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

from yoke_core.engines import done_transition
from yoke_core.engines import done_transition_gates
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_session,
    tmp_db,  # noqa: F401 — fixture re-export
)

from yoke_core.engines._done_transition_test_helpers import (
    _insert_item,
    connect_dt_db,
    dt_db,
)


class TestRunQaGates:
    """TC-run-qa-gates: blocking QA requirement check."""

    def test_unsatisfied_blocking_qa_blocks(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r5', 1, 'succeeded', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES ('r5', 'smoke-test', 1, 'failed')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_qa_gates("r5") is True

    def test_all_passed_qa_passes(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r6', 1, 'succeeded', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES ('r6', 'smoke-test', 1, 'passed')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_qa_gates("r6") is False

    def test_waived_qa_passes(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, created_at) "
            "VALUES ('r7', 1, 'succeeded', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO deployment_run_qa (run_id, check_name, blocking, status) "
            "VALUES ('r7', 'smoke-test', 1, 'waived')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_qa_gates("r7") is False


class TestEmptyBranchGuard:
    """TC-empty-branch: empty worktree branch guard."""

    def test_no_worktree_passes(self):
        code = done_transition._check_empty_branch("", Path("/tmp"), "main", 42)
        assert code is None

    def test_run_skips_empty_branch_guard_when_branch_already_merged(self, dt_db):
        db_path, _ = dt_db
        repo_root = db_path.parent
        _insert_item(db_path, 42, status="implemented")

        with (
            mock.patch.object(done_transition, "_resolve_repo_root", return_value=repo_root),
            mock.patch.object(done_transition, "_resolve_project_context", return_value=(repo_root, "")),
            mock.patch.object(done_transition, "_get_base_branch", return_value="main"),
            mock.patch.object(done_transition, "_check_merge_guard", return_value=True),
            mock.patch.object(done_transition, "_verify_recovery_evidence", return_value=True),
            mock.patch.object(done_transition, "_check_empty_branch") as mock_empty,
            mock.patch.object(done_transition, "_cleanup_stale_branches"),
            mock.patch.object(done_transition, "_verify_cwd_after_merge", return_value=repo_root),
            mock.patch.object(done_transition, "_schema_gate"),
            mock.patch.object(done_transition, "_check_deployment_flow_guard", return_value=None),
            mock.patch.object(done_transition, "_cross_project_commit_guard"),
            mock.patch.object(done_transition, "_populate_merged_at"),
            mock.patch.object(done_transition, "_update_status_to_done", return_value=True),
            mock.patch.object(done_transition, "_finalize_done_local_side_effects"),
            mock.patch.object(done_transition, "_update_item_direct", return_value=0),
            mock.patch.object(done_transition, "_rebuild_board_direct"),
            mock.patch.object(done_transition, "_sync_done_item_direct"),
        ):
            rc = done_transition.run(42)

        assert rc == 0
        mock_empty.assert_not_called()


class TestSimulationGate:
    """TC-simulation-gate: Integration simulation gate for epics."""

    def test_skip_simulation_passes(self, dt_db):
        with mock.patch("yoke_core.engines.done_transition_gates.check_epic_simulation_gate") as mock_gate:
            code = done_transition._check_simulation_gate(42, skip=True)
        assert code is None
        mock_gate.assert_not_called()

    def test_passing_gate_returns_none(self, dt_db):
        gate = mock.Mock(passed=True)
        with mock.patch("yoke_core.engines.done_transition_gates.check_epic_simulation_gate", return_value=gate) as mock_gate:
            code = done_transition._check_simulation_gate(42, skip=False)
        assert code is None
        gate.emit_errors.assert_not_called()
        mock_gate.assert_called_once()

    def test_failing_gate_blocks_and_emits_errors(self, dt_db):
        gate = mock.Mock(passed=False)
        with mock.patch("yoke_core.engines.done_transition_gates.check_epic_simulation_gate", return_value=gate):
            code = done_transition._check_simulation_gate(43, skip=False)
        assert code == 3
        gate.emit_errors.assert_called_once()


# ---------------------------------------------------------------------------
# Ephemeral env cleanup tests
# ---------------------------------------------------------------------------


class TestLocalDoneFinalization:
    """TC-ephemeral-cleanup: local done finalization."""

    def test_marks_non_stopped_envs(self, dt_db, capsys):
        db_path, _ = dt_db
        _insert_item(db_path, 60)
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO ephemeral_environments (id, item, status) "
            "VALUES (1, 'YOK-60', 'running')"
        )
        conn.execute(
            "INSERT INTO ephemeral_environments (id, item, status) "
            "VALUES (2, 'YOK-60', 'stopped')"
        )
        conn.commit()
        conn.close()

        done_transition._finalize_done_local_side_effects(
            60,
            "issue",
            "Test item",
            "yoke",
            "",
        )

        captured = capsys.readouterr()
        assert "stopped 1 ephemeral env(s)" in captured.out
        conn = connect_dt_db(db_path)
        status, stopped_at = conn.execute(
            "SELECT status, stopped_at FROM ephemeral_environments WHERE id = 1"
        ).fetchone()
        conn.close()
        assert status == "stopped"
        assert stopped_at


# ---------------------------------------------------------------------------
# CLI argument parsing tests
# ---------------------------------------------------------------------------


class TestCLIParsing:
    """TC-cli-parsing: CLI argument parsing."""

    def test_plain_number(self, dt_db):
        with mock.patch.object(done_transition, "run", return_value=0) as mock_run:
            done_transition.main(["42"])
        mock_run.assert_called_once_with(
            42, env_name="", skip_simulation=False,
            skip_deploy=False, skip_qa=False,
        )

    def test_sun_prefix_stripped(self, dt_db):
        with mock.patch.object(done_transition, "run", return_value=0) as mock_run:
            done_transition.main(["YOK-042"])
        mock_run.assert_called_once_with(
            42, env_name="", skip_simulation=False,
            skip_deploy=False, skip_qa=False,
        )

    def test_all_flags(self, dt_db):
        with mock.patch.object(done_transition, "run", return_value=0) as mock_run:
            done_transition.main([
                "99", "--env", "staging",
                "--skip-simulation", "--skip-deploy", "--skip-qa",
            ])
        mock_run.assert_called_once_with(
            99, env_name="staging", skip_simulation=True,
            skip_deploy=True, skip_qa=True,
        )

    def test_missing_item_returns_usage_error(self, dt_db, capsys):
        rc = done_transition.main([])
        assert rc == 2
        captured = capsys.readouterr()
        assert "Usage" in captured.err


# ---------------------------------------------------------------------------
# Recovery gap absorption tests
# ---------------------------------------------------------------------------


class TestRecoveryGapAbsorption:
    """TC-recovery-gaps: recovery gaps absorbed."""

    def test_empty_branch_message_includes_evidence_only_guidance(self):
        """Empty branch error must explain evidence-only recovery."""
        # We test the message content from _check_empty_branch by capturing stderr
        import io
        import contextlib

        f = io.StringIO()
        with contextlib.redirect_stderr(f):
            # Mock git to return 0 commits
            with mock.patch.object(done_transition, "_run_git") as mock_git:
                # rev-parse --verify succeeds
                mock_git.side_effect = [
                    mock.Mock(returncode=0, stdout="abc123\n"),  # verify
                    mock.Mock(returncode=0, stdout="0\n"),  # rev-list --count
                ]
                code = done_transition._check_empty_branch(
                    "YOK-99", Path("/tmp"), "main", 99
                )

        stderr_output = f.getvalue()
        assert code == 8
        assert "evidence-only" in stderr_output
        assert "--no-worktree" in stderr_output
        # Field-note 8728: recovery hint teaches the canonical agent shape
        # (`yoke items scalar update --null`), not the legacy db_router
        # write that silently stores the literal string "null".
        assert "yoke items scalar update" in stderr_output
        assert "--field worktree" in stderr_output
        assert "--null" in stderr_output
        # Ensure the broken shape is gone.
        assert "db_router items update" not in stderr_output
        assert "worktree null\n" not in stderr_output

    def test_deployment_flow_guard_variants_all_documented(self):
        """All exit 7 variants must be reachable in the guard surfaces."""
        import inspect
        # Redirect path lives in its own function
        redirect_src = inspect.getsource(done_transition._check_deployment_redirect)
        assert "deployment flow" in redirect_src
        # Skip-deploy + blocking-QA + deploy-stage variants live in the post-merge guard
        guard_src = inspect.getsource(done_transition._check_deployment_flow_guard)
        assert "_check_deployment_flow_guard" in guard_src
        assert "skip_deploy" in guard_src
        assert "deploy_stage" in guard_src


# ---------------------------------------------------------------------------
# Merge guard tests
# ---------------------------------------------------------------------------


class TestMergeGuard:
    """TC-merge-guard: Branch merge detection."""

    def test_no_worktree_not_merged(self):
        result = done_transition._check_merge_guard("", Path("/tmp"), "main")
        assert result is False

    def test_missing_branch_treated_as_merged(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.return_value = mock.Mock(returncode=128, stdout="")
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True

    def test_ancestry_check_detects_merged(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout="abc\n"),  # rev-parse branch
                mock.Mock(returncode=0, stdout=""),       # fetch origin main
                mock.Mock(returncode=0, stdout="def\n"),  # rev-parse origin/main
                mock.Mock(returncode=0, stdout=""),       # ancestry vs origin/main
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True

    def test_squash_merge_detected(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout="abc\n"),  # rev-parse branch
                mock.Mock(returncode=0, stdout=""),       # fetch origin main
                mock.Mock(returncode=0, stdout="def\n"),  # rev-parse origin/main
                mock.Mock(returncode=1, stdout=""),       # ancestry fails
                mock.Mock(returncode=0, stdout="abc123 Merge YOK-9999\n"),  # log grep
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True

# Origin-ref ancestry coverage and `_verify_recovery_evidence` tests live in
# test_done_transition_origin_evidence.py.


# ---------------------------------------------------------------------------
# Workflow helpers ported from test-done-transition-gaps.sh
# (shell suite retired). These cover the post-merge bookkeeping paths that
# the existing guard-focused test classes above do not exercise.
# ---------------------------------------------------------------------------

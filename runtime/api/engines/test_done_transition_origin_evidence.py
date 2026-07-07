"""Origin-based ancestry guard and recovery-evidence verification.

These tests exercise the production-ref symmetry between
`_check_merge_guard` and the merge engine's own already-merged guard, plus
the defense-in-depth `_verify_recovery_evidence` that gates
`resume_from_step6`. Both surfaces fetch origin and compare against
`origin/<base_branch>` so a local base ref that has drifted ahead of
origin cannot short-circuit a merge that hasn't landed yet.

Sibling test_done_transition_gates.py holds the pre-existing happy-path
guard coverage; this file holds the origin-symmetry regression suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.engines import done_transition


class TestMergeGuardOriginAncestry:
    """Origin-ref ancestry/squash coverage for `_check_merge_guard`."""

    def test_stale_local_ancestry_does_not_false_positive(self):
        """Regression: local base ahead of origin must not flip the guard.

        Prior shape — done-transition's ancestry check ran against the
        local base ref only. If local main happened to contain the branch
        tip (e.g., from a prior rebase or a previous fast-forward that
        never pushed), the guard returned True and the merge step was
        skipped, leaving the PR unmerged on GitHub. The operator then had
        to recover the worktree from the preserved commit and rerun the
        merge engine.
        """
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout="abc\n"),  # rev-parse branch
                mock.Mock(returncode=0, stdout=""),       # fetch origin main
                mock.Mock(returncode=0, stdout="def\n"),  # rev-parse origin/main
                mock.Mock(returncode=1, stdout=""),       # ancestry vs origin/main FAILS
                mock.Mock(returncode=0, stdout=""),       # log grep — no squash evidence
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is False

    def test_origin_ref_missing_falls_back_to_local(self):
        """No remote available (test envs) falls back to local base ref."""
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout="abc\n"),  # rev-parse branch
                mock.Mock(returncode=128, stdout=""),     # fetch fails
                mock.Mock(returncode=128, stdout=""),     # rev-parse origin/main fails
                mock.Mock(returncode=0, stdout=""),       # ancestry vs local main succeeds
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True


class TestVerifyRecoveryEvidence:
    """Defense-in-depth for resume_from_step6: refuse fraudulent recovery."""

    def test_evidence_present_returns_true(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),        # fetch
                mock.Mock(returncode=0, stdout="def\n"),   # rev-parse origin/main
                mock.Mock(returncode=0, stdout="abc123 YOK-1700 commit\n"),
            ]
            result = done_transition._verify_recovery_evidence(
                1700, Path("/tmp"), "main"
            )
        assert result is True

    def test_evidence_absent_returns_false(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),       # fetch
                mock.Mock(returncode=0, stdout="def\n"),  # rev-parse origin/main
                mock.Mock(returncode=0, stdout=""),       # log grep — empty
            ]
            result = done_transition._verify_recovery_evidence(
                9999, Path("/tmp"), "main"
            )
        assert result is False

    def test_origin_ref_missing_falls_back_to_local(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=128, stdout=""),     # fetch fails
                mock.Mock(returncode=128, stdout=""),     # rev-parse origin/main fails
                mock.Mock(returncode=0, stdout="abc YOK-42\n"),  # log on local main
            ]
            result = done_transition._verify_recovery_evidence(
                42, Path("/tmp"), "main"
            )
        assert result is True

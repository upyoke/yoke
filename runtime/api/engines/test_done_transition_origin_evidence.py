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


class TestRecoveryEvidenceSearchKeys:
    """What the recovery guard greps for must identify THIS item.

    The keys are search keys, not display text. A guard that searches the
    generic unresolved phrase matches nothing in the ordinary case and, in
    the case where some commit message quotes it, accepts an unrelated
    merge as this item's evidence.
    """

    def _greps(self, mock_git) -> list[str]:
        return [
            arg
            for call in mock_git.call_args_list
            for arg in call.args[0]
            if isinstance(arg, str) and arg.startswith("--grep=")
        ]

    def test_searches_the_public_ref_and_the_legacy_identity(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),   # fetch origin main
                mock.Mock(returncode=0, stdout="a\n"),  # rev-parse origin/main
                mock.Mock(returncode=0, stdout=""),   # grep public ref — miss
                mock.Mock(returncode=0, stdout=""),   # grep legacy identity — miss
            ]
            found = done_transition._verify_recovery_evidence(
                4242, Path("/tmp"), "main", public_ref="YOK-77",
            )

        assert found is False
        assert self._greps(mock_git) == ["--grep=YOK-77", "--grep=YOK-4242"]

    def test_never_searches_the_generic_unresolved_phrase(self):
        """Without a public ref it still searches this item, not a phrase."""
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),   # fetch origin main
                mock.Mock(returncode=0, stdout="a\n"),  # rev-parse origin/main
                mock.Mock(returncode=0, stdout=""),   # grep legacy identity — miss
            ]
            found = done_transition._verify_recovery_evidence(
                4242, Path("/tmp"), "main",
            )

        assert found is False
        greps = self._greps(mock_git)
        assert greps == ["--grep=YOK-4242"]
        assert not any("unresolved item ref" in grep for grep in greps)

    def test_a_legacy_named_merge_commit_is_still_found(self):
        """The historical lookup this guard exists for keeps working."""
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout=""),   # fetch origin main
                mock.Mock(returncode=0, stdout="a\n"),  # rev-parse origin/main
                mock.Mock(returncode=0, stdout=""),   # grep public ref — miss
                mock.Mock(returncode=0, stdout="9f2 Merge branch 'YOK-4242'\n"),
            ]
            found = done_transition._verify_recovery_evidence(
                4242, Path("/tmp"), "main", public_ref="YOK-77",
            )

        assert found is True

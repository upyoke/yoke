"""Branch-state detection tests for done-transition merge guards."""

from pathlib import Path
from unittest import mock

from yoke_core.engines import done_transition


class TestMergeGuard:
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
                mock.Mock(returncode=0, stdout="abc\n"),
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout="def\n"),
                mock.Mock(returncode=0, stdout=""),
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True

    def test_squash_merge_detected(self):
        with mock.patch.object(done_transition, "_run_git") as mock_git:
            mock_git.side_effect = [
                mock.Mock(returncode=0, stdout="abc\n"),
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout="def\n"),
                mock.Mock(returncode=1, stdout=""),
                mock.Mock(returncode=0, stdout="abc123 Merge YOK-9999\n"),
            ]
            result = done_transition._check_merge_guard(
                "YOK-9999", Path("/tmp"), "main"
            )
        assert result is True

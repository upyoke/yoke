"""Divergence handling, post-merge checkout, and post-merge cleanup tests.

Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

# ruff: noqa: F811

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    _git,
    _write_file,
    merge_env,  # re-export fixture for this test module  # noqa: F401
    run_merge,
)


# ===========================================================================
# Tests: Divergence handling
# ===========================================================================
class TestDivergenceHandling:
    """Generated-files-only divergence auto-resolves."""

    def test_yok602_multi_commit_board_empty(self, merge_env: MergeEnv) -> None:
        """Multi-commit with BOARD.md changes merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v1)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: board regen v1")
        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature v2)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: board regen v2")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main v1)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "chore: board update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0


# ===========================================================================
# Tests: Post-merge checkout
# ===========================================================================
class TestPostMergeCheckout:
    """Repo ends on target branch after merge."""


    def test_non_target_branch_is_corrected(self, merge_env: MergeEnv) -> None:
        """A different checked-out branch is switched back to the target."""
        _git(merge_env.repo, "checkout", "-b", "unrelated-checkout")
        before = _git(merge_env.repo, "branch", "--show-current")
        assert before.stdout.strip() == "unrelated-checkout"
        result = run_merge(merge_env)
        assert result.exit_code == 0

        head = _git(merge_env.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        assert head.stdout.strip() == "main"
        assert "not 'main'. Switching." in result.stderr
        assert "YOKE_REPO_ROOT=" in result.stdout


# ===========================================================================
# Tests: post-merge cleanup
# ===========================================================================

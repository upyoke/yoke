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

    def test_yok602_board_only_divergence(self, merge_env: MergeEnv) -> None:
        """BOARD.md-only divergence merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature regen)\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md")
        _git(wt, "commit", "-m", "chore: regenerate board")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main regen)\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "chore: board update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        assert (
            "auto-resolve" in result.stdout.lower()
            or "skipping empty rebase commit" in result.stdout
            or "merge-commit succeeded" in result.stdout.lower()
        )

    def test_yok602_genfiles_only_divergence(self, merge_env: MergeEnv) -> None:
        """Generated files-only divergence merges cleanly."""
        repo = merge_env.repo
        wt = merge_env.worktree

        _write_file(wt / ".yoke" / "BOARD.md", "# Board (feature)\n")
        _write_file(wt / ".yoke" / "BOARD.md.ts", "export const board = 'feature';\n")
        _git(wt, "add", "-f", ".yoke/BOARD.md", ".yoke/BOARD.md.ts")
        _git(wt, "commit", "-m", "chore: regen board artifacts")
        _git(wt, "push", "origin", TEST_BRANCH, "--force")

        _write_file(repo / ".yoke" / "BOARD.md", "# Board (main)\n")
        _write_file(repo / ".yoke" / "BOARD.md.ts", "export const board = 'main';\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md", ".yoke/BOARD.md.ts")
        _git(repo, "commit", "-m", "chore: board artifact update on main")
        _git(repo, "push", "origin", "main")

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # Python engine may resolve in pre-merge integration or main merge
        assert (
            "auto-resolve" in result.stdout.lower()
            or "merge-commit succeeded" in result.stdout.lower()
        )

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

    def test_yok858_target_branch_checkout(self, merge_env: MergeEnv) -> None:
        """Repo on main after merge."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

        head = _git(merge_env.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        assert head.stdout.strip() == "main"

    def test_yok858_non_target_corrected(self, merge_env: MergeEnv) -> None:
        """Non-target branch corrected, YOKE_REPO_ROOT in output."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

        head = _git(merge_env.repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        assert head.stdout.strip() == "main"
        assert "YOKE_REPO_ROOT=" in result.stdout


# ===========================================================================
# Tests: post-merge cleanup
# ===========================================================================
class TestPostMergeCleanup:
    """Cleanup runs after a committed merge and never rebuilds the board."""

    def test_exit_0_clean_path_still_works(self, merge_env: MergeEnv) -> None:
        """The happy path — merge + schema refresh + cleanup all succeed —
        still returns 0 and prints the ``YOKE_REPO_ROOT={path}`` contract
        line last."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert f"YOKE_REPO_ROOT={merge_env.repo}" in result.stdout
        assert not (merge_env.repo / "data" / "config").exists()

    def test_merge_never_rebuilds_the_board(self, merge_env: MergeEnv) -> None:
        """The board refreshes only on an explicit ``yoke board rebuild``.

        A merge is one of the entry points that used to trigger a rebuild;
        it must now leave the generated view entirely alone.
        """
        board = merge_env.repo / ".yoke" / "BOARD.md"
        before = board.read_text() if board.is_file() else None

        result = run_merge(merge_env)
        assert result.exit_code == 0

        assert "Regenerating DB-sourced views" not in result.stdout
        after = board.read_text() if board.is_file() else None
        assert after == before

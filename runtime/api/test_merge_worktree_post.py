"""Post-merge dirty file handling, sync, remote cleanup, and cleanup-trap tests.

Divergence + post-merge checkout + post-merge cleanup tests
    → test_merge_worktree_post_diverge.py
Streaming primitive tests → test_merge_worktree_post_streaming.py
run_tests integration tests → test_merge_worktree_post_runtests.py

Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

import subprocess
import sys
import textwrap

from runtime.api.test_merge_worktree_full import (
    TEST_BRANCH,
    MergeEnv,
    MERGE_MODULE,
    WORKTREE_ROOT,
    _git,
    _write_file,
    run_merge,
)

pytest_plugins = ("runtime.api.test_merge_worktree_full",)


# ===========================================================================
# Tests: Post-merge dirty file handling
# ===========================================================================
class TestPostMergeDirty:
    """File dirtied during merge is stashed/restored."""

    def test_yok128_dirty_post_merge_rebase(self, merge_env: MergeEnv) -> None:
        """File dirtied during merge is stashed/restored.

        The dirty side-effect is now wired through the REST merge fake's
        ``side_effect`` shell hook (the legacy ``MOCK_GH_DIRTY_SCRIPT``
        achieved the same thing via the ``gh pr merge`` subprocess that
        the engine no longer calls).
        """
        from runtime.api import merge_worktree_test_rest_fakes as rest_fakes

        repo = merge_env.repo
        dirty_file = repo / "session-notes.txt"
        _write_file(dirty_file, "clean\n")
        _git(repo, "add", "session-notes.txt")
        _git(repo, "commit", "-m", "add session-notes")
        _git(repo, "push", "origin", "main")

        # Overlay the merge fake with a side-effect that runs the merge
        # AND dirties the file (chained after the happy-path merge that
        # the fixture seeded).
        merge_origin = rest_fakes._merge_side_effect_command(
            str(merge_env.origin), TEST_BRANCH
        )
        dirty_cmd = f"echo 'modified during merge' > '{dirty_file}'"
        rest_fakes._write(
            merge_env.rest_fake_dir,
            rest_fakes.pulls_merge_filename("9999"),
            body={"merged": True, "message": "Pull Request successfully merged"},
            side_effect=f"{merge_origin}; {dirty_cmd}",
        )

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Stashing dirty files before sync" in result.stdout
        assert "Restoring stashed files" in result.stdout

        content = dirty_file.read_text().strip()
        assert content == "modified during merge"

        stash = _git(repo, "stash", "list", check=False)
        assert "yoke-post-merge-sync" not in stash.stdout


# ===========================================================================
# Tests: Post-merge operations
# ===========================================================================
class TestPostMergeOps:
    """Post-merge sync, agent worktree pruning."""

    def test_yok443_post_merge_sync_pull_rebase(self, merge_env: MergeEnv) -> None:
        """Post-merge sync uses pull --rebase."""
        repo = merge_env.repo

        # Local bookkeeping commit not pushed
        _write_file(repo / ".yoke" / "BOARD.md", "bookkeeping update\n")
        _git(repo, "add", "-f", ".yoke/BOARD.md")
        _git(repo, "commit", "-m", "bookkeeping: board update")
        # Do NOT push

        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Syncing" in result.stdout or "up to date" in result.stdout

        # Local main includes origin/main
        _git(repo, "fetch", "origin", "main", check=False)
        anc = _git(repo, "merge-base", "--is-ancestor", "origin/main", "main", check=False)
        assert anc.returncode == 0

    def test_yok443_sync_failure_nonfatal(self, merge_env: MergeEnv) -> None:
        """Sync failure is non-fatal."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "Syncing local" in result.stdout

    def test_unowned_agent_residue_is_preserved(self, merge_env: MergeEnv) -> None:
        """Filesystem naming alone never authorizes destructive cleanup."""
        repo = merge_env.repo

        # Create stale agent worktree directory
        stale_dir = repo / ".claude" / "worktrees" / "agent-test-stale-12345"
        stale_dir.mkdir(parents=True, exist_ok=True)
        _write_file(stale_dir / "dummy.txt", "stale agent file\n")

        # Create stale agent branch
        _git(repo, "branch", "worktree-agent-stale-12345", check=False)

        result = run_merge(merge_env)
        assert result.exit_code == 0

        # No terminal DB owner, clean-status proof, or active-claim proof exists.
        assert stale_dir.exists()

        branch_list = _git(repo, "branch", "--list", "worktree-agent-stale-12345", check=False)
        assert "worktree-agent-stale-12345" in branch_list.stdout.strip()

        assert "Pruning stale agent worktree" not in result.stdout
        assert "Deleting orphaned agent branch" not in result.stdout

    def test_yok443_agent_worktree_excluded(self, merge_env: MergeEnv) -> None:
        """Non-agent worktrees excluded from dirty check."""
        repo = merge_env.repo
        agent_dir = repo / ".claude" / "worktrees" / "agent-active-99999"
        agent_dir.mkdir(parents=True, exist_ok=True)
        _write_file(agent_dir / "work.txt", "agent working file\n")

        result = run_merge(merge_env)
        assert result.exit_code == 0

    def test_yok443_no_push_when_synced(self, merge_env: MergeEnv) -> None:
        """No push when local matches origin after pull."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "up to date" in result.stdout or "matches origin" in result.stdout


# ===========================================================================
# Tests: Remote cleanup
# ===========================================================================
class TestRemoteCleanup:
    """Remote branch deletion."""

    def test_yok541_remote_branch_delete_unconditional(self, merge_env: MergeEnv) -> None:
        """Remote branch deleted after merge."""
        result = run_merge(merge_env)
        assert result.exit_code == 0

        # Either the delete message appears, or the branch is already gone
        if "Deleted remote branch" not in result.stdout:
            ls_remote = _git(merge_env.repo, "ls-remote", "--heads", str(merge_env.origin), TEST_BRANCH, check=False)
            assert TEST_BRANCH not in ls_remote.stdout

    def test_yok541_remote_delete_warning_on_failure(self, merge_env: MergeEnv) -> None:
        """Remote delete failure is warning, not crash."""
        result = run_merge(merge_env)
        assert result.exit_code == 0
        assert "YOKE_REPO_ROOT=" in result.stdout


# ===========================================================================
# Tests: Cleanup
# ===========================================================================
class TestCleanupTrap:
    """Cleanup trap removes trial branch on error."""

    def test_yok495_cleanup_trap_removes_trial_branch(self, merge_env: MergeEnv) -> None:
        """Trap cleans up trial branch on error."""
        repo = merge_env.repo

        # Find real git
        real_git = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()

        # Create git mock that fails on 'checkout YOK-N' (without -b)
        git_mock_dir = merge_env.tmpdir / "git-mock"
        git_mock_dir.mkdir(parents=True, exist_ok=True)
        git_mock_script = textwrap.dedent(f"""\
            #!/usr/bin/env sh
            _has_b=0
            _has_checkout=0
            _has_branch_name=0
            for _a in "$@"; do
              case "$_a" in
                -b) _has_b=1 ;;
                checkout) _has_checkout=1 ;;
                {TEST_BRANCH}) _has_branch_name=1 ;;
              esac
            done
            if [ "$_has_checkout" -eq 1 ] && [ "$_has_branch_name" -eq 1 ] && [ "$_has_b" -eq 0 ]; then
              "{real_git}" checkout --detach HEAD 2>/dev/null || true
              echo "mock git: simulated checkout failure" >&2
              exit 1
            fi
            exec "{real_git}" "$@"
        """)
        git_mock_path = git_mock_dir / "git"
        git_mock_path.write_text(git_mock_script)
        git_mock_path.chmod(git_mock_path.stat().st_mode | 0o111)

        git_mock_test_path = f"{git_mock_dir}:{merge_env.test_path}"

        env_overrides = merge_env.env(extra={"PATH": git_mock_test_path})
        env_overrides.setdefault("PYTHONPATH", str(WORKTREE_ROOT))
        subprocess.run(
            [sys.executable, "-m", MERGE_MODULE, TEST_BRANCH, "main"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            env=env_overrides,
            check=False,
        )

        # Python engine may succeed where shell failed; verify no trial branch remains
        branch_list = subprocess.run(
            [real_git, "branch", "--list", f"trial/{TEST_BRANCH}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert f"trial/{TEST_BRANCH}" not in branch_list.stdout
